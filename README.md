# BeeHive Rental — динамический Backend + PostgreSQL

Эта версия `main.py` заменяет демонстрационные Python-словари из
`Hive_Project2/main.py` настоящими SQL-запросами к PostgreSQL 17.
Ранее существовавшие API-адреса сохранены, дополнительно добавлены методы
для пользователей, просмотра аренды и проверки базы данных.

## 1. Подготовить базу

В **PostgreSQL 17 (порт 5433)** создайте `beehive_api_db` в pgAdmin 4.
Откройте Query Tool **именно этой базы** и выполните `beehive_api_db.sql`.
Скрипт создаёт `users`, `hives`, `subscriptions`, `telemetry_logs` и тестовые записи.
Не выполняйте его в служебной базе `postgres` или старой `beehive_db`.

## 2. Установить Python-библиотеки (Windows PowerShell)

Откройте эту папку в VS Code / PyCharm и запустите терминал:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

В файле `.env` замените только `DB_PASSWORD` на пароль, заданный во время
установки **нового PostgreSQL 17**. Пароль никому не присылайте и `.env`
не загружайте в GitHub.

## 3. Запустить Backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Откройте <http://127.0.0.1:8000/docs>.
Сначала выберите **GET /api/v1/health/db → Try it out → Execute**.
Ожидается:

```json
{"status":"ok","database":"beehive_api_db","username":"postgres"}
```

Если сервер не запускается или возвращает ошибку 503:

- `password authentication failed` — проверьте `DB_PASSWORD` в `.env`;
- `connection refused` — проверьте, что сервер PostgreSQL 17 работает на `5433`;
- `relation "hives" does not exist` — выполните SQL-скрипт в `beehive_api_db`;
- если `8000` занят — укажите `--port 8001` и откройте `/docs` на нём.

## 4. Проверить ДИНАМИЧЕСКУЮ запись

В Swagger откройте **POST /api/v1/hives → Try it out** и отправьте:

```json
{
  "name": "Hive KZ-04",
  "location": "Косшы, тестовая пасека",
  "camera_url": "https://video.example.com/hls/hive-kz-04.m3u8"
}
```

Должен вернуться HTTP 201 с новым `hive_id` и `status: AVAILABLE`.

Сразу после этого в pgAdmin, Query Tool для `beehive_api_db`, выполните:

```sql
SELECT id, name, location, status FROM hives ORDER BY id;
```

**Новый улей должен появиться в PostgreSQL.** Перезапустите FastAPI и вызовите
GET `/api/v1/hives`: запись должна остаться.

Второй тест: через **POST /api/v1/hives/{hive_id}/telemetry** отправьте данные
для нового ID улья, например:

```json
{"temperature_c":35.5,"humidity_percent":62.4,"weight_kg":42.8,"noise_level_db":48.2}
```

Проверьте в pgAdmin:

```sql
SELECT * FROM telemetry_logs ORDER BY id DESC LIMIT 5;
```

Третий тест: через **POST /api/v1/subscriptions/rent** арендуйте доступный
`hive-002` пользователем `user-001`:

```json
{"user_id":"user-001","hive_id":"hive-002","duration_months":6}
```

Проверка:

```sql
SELECT * FROM subscriptions ORDER BY starts_at DESC;
SELECT id, status, subscription_user_id FROM hives ORDER BY id;
```

Теперь запись аренды и статус улья сохраняются одной транзакцией.

## 5. Как подключает Frontend-разработчик

Форма на сайте не должна подключаться к PostgreSQL и хранить пароль базы.
Frontend отправляет HTTP-запросы на FastAPI, например:

```javascript
const response = await fetch("http://127.0.0.1:8000/api/v1/hives", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Hive KZ-05",
    location: "Новая пасека",
    camera_url: "https://example.com/camera.m3u8"
  })
});
if (!response.ok) throw new Error(`API error ${response.status}`);
const newHive = await response.json();
```

При разработке на одном компьютере запрос к `127.0.0.1:8000` сработает.
**Если сайт работает на другом компьютере**, `127.0.0.1` указывает уже на
другой компьютер; понадобится доступный адрес Backend, правильный CORS и
настройка сети. Пароль PostgreSQL во Frontend никогда не передаётся.

## API-адреса

| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/v1/health/db` | Проверить PostgreSQL |
| GET / POST | `/api/v1/users` | Пользователи |
| GET / POST | `/api/v1/hives` | Просмотр/добавление ульев |
| GET | `/api/v1/hives/{hive_id}` | Улей по ID |
| GET / POST | `/api/v1/hives/{hive_id}/telemetry` | Показания датчиков |
| POST | `/api/v1/subscriptions/rent` | Аренда улья |
| GET | `/api/v1/users/{user_id}/my-hives` | Ульи пользователя |
| GET | `/api/v1/users/{user_id}/subscriptions` | История аренды |

## Ограничения демонстрационной версии

- У приложения ещё нет полноценной регистрации, входа и проверки прав доступа.
- `user_id` пока передаётся клиентом; в реальном сервисе нужен авторизованный пользователь.
- IoT-устройства должны аутентифицироваться перед отправкой телеметрии.
- URL камер в тестовых данных — примеры, не настоящие трансляции.
- `duration_months` сохраняет логику исходного кода: один месяц = 30 дней.
- Старые демо-ульи `hive-001` и `hive-003` отмечены как RENTED, хотя исходный
  `main.py` не содержал записей в словаре `subscriptions` для них.
- Не выкладывайте эту демоверсию публично без аутентификации и защиты API.
