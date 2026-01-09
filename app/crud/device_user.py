# app/crud/device_user.py
from app.crud.base import CRUDBase
from app.models.device_user import DeviceUser
from app.schemas.device_user import DeviceUserCreate, DeviceUserUpdate


class CRUDDeviceUser(CRUDBase[DeviceUser, DeviceUserCreate, DeviceUserUpdate]):
    pass


device_user = CRUDDeviceUser(DeviceUser)
