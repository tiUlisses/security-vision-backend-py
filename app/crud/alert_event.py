# app/crud/alert_event.py
from app.crud.base import CRUDBase
from app.models.alert_event import AlertEvent
from app.schemas.alert_event import (
    AlertEventCreate,
    AlertEventUpdate,
)


class CRUDAlertEvent(CRUDBase[AlertEvent, AlertEventCreate, AlertEventUpdate]):
    # Se quiser helpers específicos depois (ex: get_open_for_device+tag), coloca aqui
    pass


alert_event = CRUDAlertEvent(AlertEvent)