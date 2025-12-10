# app/api/routes/devices/__init__.py
from fastapi import APIRouter

from .base import router as base_router
from .gateways import router as gateways_router
from .cameras import router as cameras_router

router = APIRouter()

# Rotas genéricas de devices (CRUD)
router.include_router(base_router, prefix="", tags=["Devices"])

# Rotas específicas de Gateways RTLS
router.include_router(gateways_router, prefix="/gateways", tags=["RTLS Gateways"])

# Rotas específicas de Câmeras
router.include_router(cameras_router, prefix="/cameras", tags=["Cameras"])
