# securityvision-position/app/api/v1/api.py
from fastapi import APIRouter

from app.api.routes import (
    buildings,
    floors,
    floor_plans,
    people,
    tags,
    collection_logs,
    dashboard,
    person_groups,
    alert_rules,
    webhooks,
    alert_events,
    positions,
    reports,
    incidents,
    auth,
    incident_rules,
    integrations_chatwoot,
    support_groups,
)

# 👉 novo import, vindo do pacote app.api.routes.devices
from app.api.routes.devices import router as devices_router

api_router = APIRouter()

api_router.include_router(
    buildings.router,
    prefix="/buildings",
    tags=["buildings"],
)
api_router.include_router(
    incident_rules.router,
    prefix="/incident-rules",
    tags=["incident_rules"],
)
api_router.include_router(
    floors.router,
    prefix="/floors",
    tags=["floors"],
)
api_router.include_router(
    incidents.router,
    prefix="/incidents",
    tags=["incidents"],
)
api_router.include_router(
    floor_plans.router,
    prefix="/floor-plans",
    tags=["floor_plans"],
)

# 👉 aqui usamos o router combinado (base + gateways + cameras)
api_router.include_router(
    devices_router,
    prefix="/devices",
    # sem tags aqui para deixar cada sub-rotas definirem as suas:
    # - "Devices"
    # - "RTLS Gateways"
    # - "Cameras"
)

api_router.include_router(
    people.router,
    prefix="/people",
    tags=["people"],
)
api_router.include_router(
    tags.router,
    prefix="/tags",
    tags=["tags"],
)
api_router.include_router(
    collection_logs.router,
    prefix="/collection-logs",
    tags=["collection_logs"],
)
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["dashboard"],
)
api_router.include_router(
    person_groups.router,
    prefix="/person-groups",
    tags=["person_groups"],
)
api_router.include_router(
    alert_rules.router,
    prefix="/alert-rules",
    tags=["alert_rules"],
)
api_router.include_router(
    webhooks.router,
    prefix="/webhooks",
    tags=["webhooks"],
)
api_router.include_router(
    alert_events.router,
    prefix="/alert-events",
    tags=["alert_events"],
)
api_router.include_router(
    positions.router,
    prefix="/positions",
    tags=["positions"],
)
api_router.include_router(
    reports.router,
    prefix="/reports",
    tags=["reports"],
)

api_router.include_router(integrations_chatwoot.router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(
    support_groups.router,
    tags=["support-groups"],
)