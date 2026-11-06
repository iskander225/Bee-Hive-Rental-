"""Smart Beehive Rental & Monitoring API.

Install: ``pip install fastapi uvicorn``
Run: ``uvicorn main:app --reload``
"""
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import AnyUrl, BaseModel, Field


class HiveStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class HiveCreate(BaseModel):
    """Payload for registering an IoT hive."""
    name: str = Field(min_length=2, max_length=100, example="Hive KZ-04")
    location: str = Field(example="Алматинская область, пасека № 2")
    camera_url: AnyUrl = Field(example="https://video.example.com/hls/hive-kz-04.m3u8")


class Hive(HiveCreate):
    """Hive information shown in the catalog and customer cabinet."""
    id: str = Field(example="hive-001")
    status: HiveStatus = Field(example=HiveStatus.RENTED)
    subscription_user_id: str | None = Field(default=None, example="user-001")


class TelemetryCreate(BaseModel):
    """Sensor packet sent by ESP32, Raspberry Pi, or a gateway."""
    temperature_c: float = Field(ge=-40, le=80, example=35.5, description="Internal temperature, °C")
    humidity_percent: float = Field(ge=0, le=100, example=62.4, description="Internal humidity, %")
    weight_kg: float = Field(gt=0, le=300, example=42.8, description="Hive weight, kg")
    noise_level_db: float = Field(ge=0, le=150, example=48.2, description="Bee activity/noise, dB")


class Telemetry(TelemetryCreate):
    """Latest telemetry with server timestamp and computed health status."""
    recorded_at: datetime = Field(example="2026-10-15T09:30:00Z")
    health_status: HealthStatus = Field(example=HealthStatus.HEALTHY)


class RentRequest(BaseModel):
    """Request to assign an available hive to an existing user."""
    user_id: str = Field(example="user-001")
    hive_id: str = Field(example="hive-002")
    duration_months: int = Field(ge=1, le=36, example=6)


class Subscription(BaseModel):
    """Created rental subscription."""
    id: str = Field(example="sub-001")
    user_id: str = Field(example="user-001")
    hive_id: str = Field(example="hive-002")
    duration_months: int = Field(example=6)
    starts_at: datetime = Field(example="2026-10-15T09:30:00Z")
    ends_at: datetime = Field(example="2027-04-15T09:30:00Z")
    active: bool = Field(example=True)


app = FastAPI(
    title="Smart Beehive Rental & Monitoring API",
    description="API сервиса аренды умных ульев с поддержкой IoT-телеметрии и видеонаблюдения.",
    version="1.0.0",
    openapi_tags=[
        {"name": "Hives", "description": "Управление ульями и видеокамерами."},
        {"name": "IoT Telemetry", "description": "Приём и просмотр показаний IoT-датчиков."},
        {"name": "Subscriptions", "description": "Аренда ульев и личный кабинет."},
    ],
)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Open the interactive Swagger UI when the service root is visited."""
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT)
def favicon() -> Response:
    """Silently handle the browser's default favicon request."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Demo in-memory database. All modifications reset after a server restart.
users = {"user-001": {"name": "Алия Нурбекова"}, "user-002": {"name": "Иван Петров"}}
hives: dict[str, dict] = {
    "hive-001": {"id": "hive-001", "name": "Hive KZ-01", "location": "Алматинская область, пасека № 1", "status": HiveStatus.RENTED, "subscription_user_id": "user-001", "camera_url": "https://video.example.com/hls/hive-kz-01.m3u8"},
    "hive-002": {"id": "hive-002", "name": "Hive KZ-02", "location": "Алматинская область, пасека № 1", "status": HiveStatus.AVAILABLE, "subscription_user_id": None, "camera_url": "https://video.example.com/hls/hive-kz-02.m3u8"},
    "hive-003": {"id": "hive-003", "name": "Hive KZ-03", "location": "Туркестанская область, пасека № 3", "status": HiveStatus.RENTED, "subscription_user_id": "user-002", "camera_url": "rtsp://camera.example.com:8554/hive-kz-03"},
}
telemetry_store: dict[str, dict] = {
    "hive-001": {"temperature_c": 35.5, "humidity_percent": 62.4, "weight_kg": 42.8, "noise_level_db": 48.2, "recorded_at": datetime.now(UTC), "health_status": HealthStatus.HEALTHY},
    "hive-002": {"temperature_c": 33.0, "humidity_percent": 78.0, "weight_kg": 39.6, "noise_level_db": 57.0, "recorded_at": datetime.now(UTC), "health_status": HealthStatus.WARNING},
    "hive-003": {"temperature_c": 38.8, "humidity_percent": 89.0, "weight_kg": 31.4, "noise_level_db": 76.0, "recorded_at": datetime.now(UTC), "health_status": HealthStatus.CRITICAL},
}
subscriptions: dict[str, dict] = {}


def require_hive(hive_id: str) -> dict:
    """Get a hive or return a standard HTTP 404 error."""
    if hive_id not in hives:
        raise HTTPException(404, f"Hive '{hive_id}' was not found")
    return hives[hive_id]


def calculate_health(data: TelemetryCreate) -> HealthStatus:
    """Derive a simple demonstrative health state from sensor thresholds."""
    if data.temperature_c < 30 or data.temperature_c > 38 or data.humidity_percent > 85 or data.noise_level_db > 70:
        return HealthStatus.CRITICAL
    if data.temperature_c < 33 or data.temperature_c > 37 or data.humidity_percent > 75 or data.noise_level_db > 55:
        return HealthStatus.WARNING
    return HealthStatus.HEALTHY


@app.get("/api/v1/hives", response_model=list[Hive], tags=["Hives"], summary="Получить список ульев")
def list_hives(availability: HiveStatus | None = Query(None, description="AVAILABLE or RENTED")) -> list[dict]:
    """List all hives, optionally filtering their rental availability."""
    return [hive for hive in hives.values() if availability is None or hive["status"] == availability]


@app.get("/api/v1/hives/{hive_id}", response_model=Hive, tags=["Hives"], summary="Получить улей по ID")
def get_hive(hive_id: Annotated[str, Path(examples=["hive-001"])]) -> dict:
    """Return hive location, subscription state, and RTSP/HLS camera URL."""
    return require_hive(hive_id)


@app.post("/api/v1/hives", response_model=Hive, status_code=status.HTTP_201_CREATED, tags=["Hives"], summary="Добавить улей")
def create_hive(payload: HiveCreate) -> dict:
    """Add a new hive as available for rent."""
    hive = {"id": f"hive-{uuid4().hex[:8]}", **payload.model_dump(mode="json"), "status": HiveStatus.AVAILABLE, "subscription_user_id": None}
    hives[hive["id"]] = hive
    return hive


@app.get("/api/v1/hives/{hive_id}/telemetry", response_model=Telemetry, tags=["IoT Telemetry"], summary="Получить актуальную телеметрию")
def get_telemetry(hive_id: Annotated[str, Path(examples=["hive-001"])]) -> dict:
    """Return the latest sensor reading for the hive."""
    require_hive(hive_id)
    if hive_id not in telemetry_store:
        raise HTTPException(404, "No telemetry has been received for this hive yet")
    return telemetry_store[hive_id]


@app.post("/api/v1/hives/{hive_id}/telemetry", response_model=Telemetry, status_code=status.HTTP_201_CREATED, tags=["IoT Telemetry"], summary="Отправить телеметрию с устройства")
def post_telemetry(hive_id: Annotated[str, Path(examples=["hive-001"])], payload: TelemetryCreate) -> dict:
    """Accept an IoT sensor packet and store its calculated health assessment."""
    require_hive(hive_id)
    telemetry_store[hive_id] = {**payload.model_dump(), "recorded_at": datetime.now(UTC), "health_status": calculate_health(payload)}
    return telemetry_store[hive_id]


@app.post("/api/v1/subscriptions/rent", response_model=Subscription, status_code=status.HTTP_201_CREATED, tags=["Subscriptions"], summary="Оформить аренду улья")
def rent_hive(payload: RentRequest) -> dict:
    """Rent one currently available hive to an existing test user."""
    if payload.user_id not in users:
        raise HTTPException(404, f"User '{payload.user_id}' was not found")
    hive = require_hive(payload.hive_id)
    if hive["status"] != HiveStatus.AVAILABLE:
        raise HTTPException(409, "Hive is already rented")
    now = datetime.now(UTC)
    subscription = {"id": f"sub-{uuid4().hex[:8]}", **payload.model_dump(), "starts_at": now, "ends_at": now + timedelta(days=30 * payload.duration_months), "active": True}
    subscriptions[subscription["id"]] = subscription
    hive.update(status=HiveStatus.RENTED, subscription_user_id=payload.user_id)
    return subscription


@app.get("/api/v1/users/{user_id}/my-hives", response_model=list[Hive], tags=["Subscriptions"], summary="Получить арендованные ульи пользователя")
def get_user_hives(user_id: Annotated[str, Path(examples=["user-001"])]) -> list[dict]:
    """Return hives assigned to a user, for their personal dashboard."""
    if user_id not in users:
        raise HTTPException(404, f"User '{user_id}' was not found")
    return [hive for hive in hives.values() if hive["subscription_user_id"] == user_id]
