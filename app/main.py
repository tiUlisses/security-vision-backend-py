# app/main.py
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.session import init_db
from app.crud.user import user as crud_user
from app.core.security import get_password_hash
from app.schemas.user import UserCreate
from app.db.session import AsyncSessionLocal
from app.services.mqtt_ingestor import MqttIngestor
from app.services.cambus_event_collector import run_cambus_event_collector  # 👈 NOVO

logger = logging.getLogger("rtls.main")

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)
origins = ["*"]

# --- CORS para o frontend Vite ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static /media ---
MEDIA_ROOT = Path(settings.media_root)
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

app.mount(
    "/media",
    StaticFiles(directory=str(MEDIA_ROOT)),
    name="media",
)

_mqtt_task: asyncio.Task | None = None
_cambus_task: asyncio.Task | None = None   # 👈 NOVO


async def _bootstrap_superadmin() -> None:
    """
    Cria o primeiro superusuário a partir das variáveis do .env
    (SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD, SUPERADMIN_NAME) apenas
    quando ainda não existe nenhum admin no banco.
    """
    if not (settings.SUPERADMIN_EMAIL and settings.SUPERADMIN_PASSWORD):
        logger.info("SUPERADMIN_EMAIL/PASSWORD não configurados; pulando bootstrap de superadmin")
        return

    async with AsyncSessionLocal() as db:
        has_admin = await crud_user.has_admin(db)
        if has_admin:
            logger.info("Bootstrap de superadmin não necessário: já existe admin no banco")
            return

        logger.info("Criando superadmin inicial a partir do .env (%s)", settings.SUPERADMIN_EMAIL)
        pwd_hash = get_password_hash(settings.SUPERADMIN_PASSWORD)
        await crud_user.create_with_hashed_password(
            db,
            obj_in=UserCreate(
                email=settings.SUPERADMIN_EMAIL,
                full_name=settings.SUPERADMIN_NAME,
                role="SUPERADMIN",
                is_active=True,
                is_superuser=True,
                password=settings.SUPERADMIN_PASSWORD,
            ),
            hashed_password=pwd_hash,
        )
        logger.info("Superadmin %s criado com sucesso", settings.SUPERADMIN_EMAIL)


@app.on_event("startup")
async def on_startup() -> None:
    global _mqtt_task, _cambus_task

    await init_db()

    await _bootstrap_superadmin()

    # 👇 Ingestor de gateways RTLS (já existia)
    if settings.MQTT_ENABLED:
        logger.info("Starting MQTT ingestor task...")
        ingestor = MqttIngestor(settings=settings)
        _mqtt_task = asyncio.create_task(ingestor.run())

    # 👇 Coletor de eventos do CAM-BUS (câmeras)
    if settings.CAMBUS_MQTT_ENABLED:
        logger.info("Starting CAM-BUS event collector task...")
        _cambus_task = asyncio.create_task(
            run_cambus_event_collector(),
            name="cambus_event_collector",
        )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _mqtt_task, _cambus_task

    # Para o ingestor de gateways
    if _mqtt_task:
        logger.info("Stopping MQTT ingestor task...")
        _mqtt_task.cancel()
        try:
            await _mqtt_task
        except asyncio.CancelledError:
            logger.info("MQTT ingestor task cancelled")

    # Para o coletor do CAM-BUS
    if _cambus_task:
        logger.info("Stopping CAM-BUS event collector task...")
        _cambus_task.cancel()
        try:
            await _cambus_task
        except asyncio.CancelledError:
            logger.info("CAM-BUS event collector task cancelled")


@app.get("/health", tags=["health"])
async def healthcheck():
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")