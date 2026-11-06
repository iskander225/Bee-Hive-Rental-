-- BeeHive Rental: PostgreSQL database schema and demo data.
-- Compatible with the data models and initial dictionaries in main.py
-- from the shared Hive_Project2 folder (15 Oct 2026).
--
-- HOW TO RUN IN pgAdmin 4:
-- 1. Connect to PostgreSQL with an account that can create databases.
-- 2. Create a new database named beehive_api_db (Databases > Create > Database).
-- 3. Select beehive_api_db > Query Tool and execute this entire file.
-- 4. The old beehive_db database is not touched.
--
-- The main.py backend currently uses in-memory Python dictionaries. This SQL
-- creates a real database; the Python code must still be changed to query it.

BEGIN;

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(150) NOT NULL
);

CREATE TABLE IF NOT EXISTS hives (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    location TEXT NOT NULL,
    camera_url TEXT NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'AVAILABLE'
        CHECK (status IN ('AVAILABLE', 'RENTED')),
    subscription_user_id VARCHAR(32) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id VARCHAR(32) PRIMARY KEY,
    user_id VARCHAR(32) NOT NULL REFERENCES users(id),
    hive_id VARCHAR(32) NOT NULL REFERENCES hives(id),
    duration_months INTEGER NOT NULL CHECK (duration_months BETWEEN 1 AND 36),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (ends_at > starts_at)
);

-- Prevent two active subscriptions for the same hive.
CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_subscription_per_hive
    ON subscriptions (hive_id) WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS telemetry_logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hive_id VARCHAR(32) NOT NULL REFERENCES hives(id) ON DELETE CASCADE,
    temperature_c DOUBLE PRECISION NOT NULL
        CHECK (temperature_c BETWEEN -40 AND 80),
    humidity_percent DOUBLE PRECISION NOT NULL
        CHECK (humidity_percent BETWEEN 0 AND 100),
    weight_kg DOUBLE PRECISION NOT NULL
        CHECK (weight_kg > 0 AND weight_kg <= 300),
    noise_level_db DOUBLE PRECISION NOT NULL
        CHECK (noise_level_db BETWEEN 0 AND 150),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    health_status VARCHAR(10) NOT NULL
        CHECK (health_status IN ('HEALTHY', 'WARNING', 'CRITICAL'))
);

CREATE INDEX IF NOT EXISTS ix_telemetry_latest
    ON telemetry_logs (hive_id, recorded_at DESC, id DESC);

-- Same two users as in the original Python main.py.
INSERT INTO users (id, name) VALUES
    ('user-001', 'Алия Нурбекова'),
    ('user-002', 'Иван Петров')
ON CONFLICT (id) DO NOTHING;

-- Same three hives and camera URLs as in the original Python main.py.
INSERT INTO hives
    (id, name, location, status, subscription_user_id, camera_url)
VALUES
    ('hive-001', 'Hive KZ-01', 'Алматинская область, пасека № 1',
     'RENTED', 'user-001', 'https://video.example.com/hls/hive-kz-01.m3u8'),
    ('hive-002', 'Hive KZ-02', 'Алматинская область, пасека № 1',
     'AVAILABLE', NULL, 'https://video.example.com/hls/hive-kz-02.m3u8'),
    ('hive-003', 'Hive KZ-03', 'Туркестанская область, пасека № 3',
     'RENTED', 'user-002', 'rtsp://camera.example.com:8554/hive-kz-03')
ON CONFLICT (id) DO NOTHING;

-- Initial readings match telemetry_store in main.py.
-- One seed reading per hive is inserted, even if this script is rerun.
INSERT INTO telemetry_logs
    (hive_id, temperature_c, humidity_percent, weight_kg,
     noise_level_db, recorded_at, health_status)
SELECT seed.hive_id, seed.temperature_c, seed.humidity_percent,
       seed.weight_kg, seed.noise_level_db, CURRENT_TIMESTAMP,
       seed.health_status
FROM (VALUES
    ('hive-001', 35.5, 62.4, 42.8, 48.2, 'HEALTHY'),
    ('hive-002', 33.0, 78.0, 39.6, 57.0, 'WARNING'),
    ('hive-003', 38.8, 89.0, 31.4, 76.0, 'CRITICAL')
) AS seed(hive_id, temperature_c, humidity_percent, weight_kg,
          noise_level_db, health_status)
WHERE NOT EXISTS (
    SELECT 1 FROM telemetry_logs t WHERE t.hive_id = seed.hive_id
);

-- The original Python program starts with subscriptions = {}, so we also
-- leave this table empty. Existing RENTED flags are copied as-is from main.py.

COMMIT;

-- Verify four tables and their number of rows (expected: 2, 3, 0, 3).
SELECT 'users' AS table_name, COUNT(*) AS row_count FROM users
UNION ALL SELECT 'hives', COUNT(*) FROM hives
UNION ALL SELECT 'subscriptions', COUNT(*) FROM subscriptions
UNION ALL SELECT 'telemetry_logs', COUNT(*) FROM telemetry_logs;

-- To retrieve the latest reading for one hive in the API later:
-- SELECT * FROM telemetry_logs WHERE hive_id = 'hive-001'
-- ORDER BY recorded_at DESC, id DESC LIMIT 1;
