"""BeeHive Rental API backed by PostgreSQL 17, based on Hive_Project2/main.py.

Install dependencies: py -m pip install -r requirements.txt
Run locally:       py -m uvicorn main:app --reload
Open Swagger:      http://127.0.0.1:8000/docs

Before running, create beehive_api_db, run beehive_api_db.sql, and set .env.
"""

import os
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Iterator
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import AnyUrl, BaseModel, Field


load_dotenv()


class HiveStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150, examples=["Алия Нурбекова"])


class User(UserCreate):
    id: str


class HiveCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100, examples=["Hive KZ-04"])
    location: str = Field(min_length=2, examples=["Алматинская область, пасека № 2"])
    camera_url: AnyUrl = Field(examples=["https://video.example.com/hls/hive-kz-04.m3u8"])


class Hive(HiveCreate):
    id: str
    status: HiveStatus
    subscription_user_id: str | None = None


class TelemetryCreate(BaseModel):
    temperature_c: float = Field(ge=-40, le=80, examples=[35.5])
    humidity_percent: float = Field(ge=0, le=100, examples=[62.4])
    weight_kg: float = Field(gt=0, le=300, examples=[42.8])
    noise_level_db: float = Field(ge=0, le=150, examples=[48.2])


class Telemetry(TelemetryCreate):
    recorded_at: datetime
    health_status: HealthStatus


class RentRequest(BaseModel):
    user_id: str = Field(examples=["user-001"])
    hive_id: str = Field(examples=["hive-002"])
    duration_months: int = Field(ge=1, le=36, examples=[6])


class Subscription(BaseModel):
    id: str
    user_id: str
    hive_id: str
    duration_months: int
    starts_at: datetime
    ends_at: datetime
    active: bool


app = FastAPI(
    title="Smart Beehive Rental & Monitoring API",
    description="Динамический API аренды ульев с PostgreSQL, IoT и видеонаблюдением.",
    version="2.0.0",
    openapi_tags=[
        {"name": "Users", "description": "Пользователи сервиса."},
        {"name": "Hives", "description": "Каталог ульев и видеокамеры."},
        {"name": "IoT Telemetry", "description": "Показания датчиков."},
        {"name": "Subscriptions", "description": "Аренда и личный кабинет."},
        {"name": "Health", "description": "Проверка доступности базы."},
    ],
)

# Add the frontend's exact URL(s) to FRONTEND_ORIGINS in .env if needed.
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def get_db() -> Iterator[Connection]:
    """One PostgreSQL connection and transaction per request.

    Successful changes are committed; on an HTTP or SQL error they roll back.
    Credentials are kept in .env, not hard-coded into main.py.
    """
    try:
        with psycopg.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "5433")),
            dbname=os.getenv("DB_NAME", "beehive_api_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            row_factory=dict_row,
            connect_timeout=5,
        ) as conn:
            yield conn
    except psycopg.OperationalError as exc:
        # The detailed driver error might include connection parameters.
        raise HTTPException(503, "PostgreSQL недоступен. Проверь .env и порт 5433.") from exc


Db = Annotated[Connection, Depends(get_db)]


def require_hive(conn: Connection, hive_id: str, *, for_update: bool = False) -> dict:
    lock = " FOR UPDATE" if for_update else ""
    hive = conn.execute("SELECT * FROM hives WHERE id = %s" + lock, (hive_id,)).fetchone()
    if hive is None:
        raise HTTPException(404, f"Hive '{hive_id}' was not found")
    return hive


def require_user(conn: Connection, user_id: str) -> None:
    if conn.execute("SELECT 1 FROM users WHERE id = %s", (user_id,)).fetchone() is None:
        raise HTTPException(404, f"User '{user_id}' was not found")


def calculate_health(data: TelemetryCreate) -> HealthStatus:
    if (
        data.temperature_c < 30
        or data.temperature_c > 38
        or data.humidity_percent > 85
        or data.noise_level_db > 70
    ):
        return HealthStatus.CRITICAL
    if (
        data.temperature_c < 33
        or data.temperature_c > 37
        or data.humidity_percent > 75
        or data.noise_level_db > 55
    ):
        return HealthStatus.WARNING
    return HealthStatus.HEALTHY


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT)
def favicon() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/health/db", tags=["Health"], summary="Проверить PostgreSQL")
def database_health(conn: Db) -> dict:
    row = conn.execute("SELECT current_database() AS database, current_user AS username").fetchone()
    return {"status": "ok", **row}


@app.get("/api/v1/users", response_model=list[User], tags=["Users"], summary="Список пользователей")
def list_users(conn: Db) -> list[dict]:
    return conn.execute("SELECT id, name FROM users ORDER BY id").fetchall()


@app.post(
    "/api/v1/users", response_model=User, status_code=status.HTTP_201_CREATED,
    tags=["Users"], summary="Добавить пользователя",
)
def create_user(payload: UserCreate, conn: Db) -> dict:
    user_id = f"user-{uuid4().hex[:8]}"
    return conn.execute(
        "INSERT INTO users (id, name) VALUES (%s, %s) RETURNING id, name",
        (user_id, payload.name),
    ).fetchone()


@app.get("/api/v1/hives", response_model=list[Hive], tags=["Hives"], summary="Список ульев")
def list_hives(conn: Db, availability: HiveStatus | None = Query(None)) -> list[dict]:
    if availability is None:
        return conn.execute("SELECT * FROM hives ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM hives WHERE status = %s ORDER BY id", (availability.value,)
    ).fetchall()


@app.get("/api/v1/hives/{hive_id}", response_model=Hive, tags=["Hives"], summary="Улей по ID")
def get_hive(hive_id: Annotated[str, Path(examples=["hive-001"])], conn: Db) -> dict:
    return require_hive(conn, hive_id)


@app.post(
    "/api/v1/hives", response_model=Hive, status_code=status.HTTP_201_CREATED,
    tags=["Hives"], summary="Добавить улей",
)
def create_hive(payload: HiveCreate, conn: Db) -> dict:
    hive_id = f"hive-{uuid4().hex[:8]}"
    return conn.execute(
        """INSERT INTO hives (id, name, location, camera_url, status, subscription_user_id)
           VALUES (%s, %s, %s, %s, 'AVAILABLE', NULL) RETURNING *""",
        (hive_id, payload.name, payload.location, str(payload.camera_url)),
    ).fetchone()


@app.get(
    "/api/v1/hives/{hive_id}/telemetry", response_model=Telemetry,
    tags=["IoT Telemetry"], summary="Последние показания датчиков",
)
def get_telemetry(hive_id: Annotated[str, Path(examples=["hive-001"])], conn: Db) -> dict:
    require_hive(conn, hive_id)
    reading = conn.execute(
        """SELECT temperature_c, humidity_percent, weight_kg, noise_level_db,
                  recorded_at, health_status
           FROM telemetry_logs WHERE hive_id = %s
           ORDER BY recorded_at DESC, id DESC LIMIT 1""",
        (hive_id,),
    ).fetchone()
    if reading is None:
        raise HTTPException(404, "No telemetry has been received for this hive yet")
    return reading


@app.post(
    "/api/v1/hives/{hive_id}/telemetry", response_model=Telemetry,
    status_code=status.HTTP_201_CREATED, tags=["IoT Telemetry"],
    summary="Сохранить новые показания датчиков",
)
def post_telemetry(
    hive_id: Annotated[str, Path(examples=["hive-001"])],
    payload: TelemetryCreate,
    conn: Db,
) -> dict:
    require_hive(conn, hive_id)
    return conn.execute(
        """INSERT INTO telemetry_logs
           (hive_id, temperature_c, humidity_percent, weight_kg,
            noise_level_db, recorded_at, health_status)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING temperature_c, humidity_percent, weight_kg,
                     noise_level_db, recorded_at, health_status""",
        (
            hive_id,
            payload.temperature_c,
            payload.humidity_percent,
            payload.weight_kg,
            payload.noise_level_db,
            datetime.now(UTC),
            calculate_health(payload).value,
        ),
    ).fetchone()


@app.post(
    "/api/v1/subscriptions/rent", response_model=Subscription,
    status_code=status.HTTP_201_CREATED, tags=["Subscriptions"],
    summary="Арендовать доступный улей",
)
def rent_hive(payload: RentRequest, conn: Db) -> dict:
    require_user(conn, payload.user_id)

    # FOR UPDATE locks the row until commit, preventing two simultaneous rentals.
    hive = require_hive(conn, payload.hive_id, for_update=True)
    if hive["status"] != HiveStatus.AVAILABLE.value:
        raise HTTPException(409, "Hive is already rented")

    now = datetime.now(UTC)
    subscription = conn.execute(
        """INSERT INTO subscriptions
           (id, user_id, hive_id, duration_months, starts_at, ends_at, active)
           VALUES (%s, %s, %s, %s, %s, %s, TRUE) RETURNING *""",
        (
            f"sub-{uuid4().hex[:8]}", payload.user_id, payload.hive_id,
            payload.duration_months, now, now + timedelta(days=30 * payload.duration_months),
        ),
    ).fetchone()
    conn.execute(
        "UPDATE hives SET status = 'RENTED', subscription_user_id = %s WHERE id = %s",
        (payload.user_id, payload.hive_id),
    )
    return subscription


@app.get(
    "/api/v1/users/{user_id}/my-hives", response_model=list[Hive],
    tags=["Subscriptions"], summary="Ульи пользователя",
)
def get_user_hives(user_id: Annotated[str, Path(examples=["user-001"])], conn: Db) -> list[dict]:
    require_user(conn, user_id)
    return conn.execute(
        "SELECT * FROM hives WHERE subscription_user_id = %s ORDER BY id", (user_id,)
    ).fetchall()


@app.get(
    "/api/v1/users/{user_id}/subscriptions", response_model=list[Subscription],
    tags=["Subscriptions"], summary="История аренды пользователя",
)
def get_user_subscriptions(
    user_id: Annotated[str, Path(examples=["user-001"])], conn: Db
) -> list[dict]:
    require_user(conn, user_id)
    return conn.execute(
        "SELECT * FROM subscriptions WHERE user_id = %s ORDER BY starts_at DESC", (user_id,)
    ).fetchall()
