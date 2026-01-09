# app/schemas/device.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DeviceBase(BaseModel):
    """
    Modelo base para QUALQUER dispositivo:
    - BLE_GATEWAY
    - CAMERA
    - ACCESS_CONTROLLER
    - (outros no futuro)
    """

    # Comum a todos
    name: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    type: str = Field("BLE_GATEWAY", max_length=32)

    # Identificação e posicionamento na planta
    code: Optional[str] = Field(None, max_length=64)
    mac_address: Optional[str] = Field(None, max_length=64)
    floor_plan_id: Optional[int] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None

    # Associação lógica ao prédio/andar
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    location_id: Optional[int] = None

    # NOVO: fabricante, modelo shard e Analytics
    manufacturer: Optional[str] = Field(None, max_length=128)
    model: Optional[str] = Field(None, max_length=128)
    shard: Optional[str] = Field(None, max_length=64)
    analytics: Optional[list[str]] = None
    # Status genérico
    last_seen_at: Optional[datetime] = None

    # Campos de rede
    ip_address: Optional[str] = Field(None, max_length=64)
    port: Optional[int] = None
    username: Optional[str] = Field(None, max_length=128)
    rtsp_url: Optional[str] = Field(None, max_length=512)
    proxy_path: Optional[str] = Field(None, max_length=255)
    central_path: Optional[str] = Field(None, max_length=255)
    record_retention_minutes: Optional[int] = None
    central_media_mtx_ip: Optional[str] = Field(None, max_length=64)

class DeviceCreate(DeviceBase):
    # opcional, usado internamente para setar last_seen_at
    last_seen_at: Optional[datetime] = None

    # senha só entra no create/update (não vai para o Read)
    password: Optional[str] = Field(None, max_length=128)


class DeviceUpdate(BaseModel):
    # Comum
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = Field(None, max_length=1024)
    type: Optional[str] = Field(None, max_length=32)

    # Identificação / posicionamento
    code: Optional[str] = Field(None, max_length=64)
    mac_address: Optional[str] = Field(None, max_length=64)
    floor_plan_id: Optional[int] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None

    # Associação prédio/andar
    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    location_id: Optional[int] = None

    # NOVO
    manufacturer: Optional[str] = Field(None, max_length=128)
    model: Optional[str] = Field(None, max_length=128)
    shard: Optional[str] = Field(None, max_length=64)
    
    # Rede
    ip_address: Optional[str] = Field(None, max_length=64)
    port: Optional[int] = None
    username: Optional[str] = Field(None, max_length=128)
    password: Optional[str] = Field(None, max_length=128)
    rtsp_url: Optional[str] = Field(None, max_length=512)
    proxy_path: Optional[str] = Field(None, max_length=255)
    central_path: Optional[str] = Field(None, max_length=255)
    record_retention_minutes: Optional[int] = None
    central_media_mtx_ip: Optional[str] = Field(None, max_length=64)

    # Status
    last_seen_at: Optional[datetime] = None

class DeviceRead(DeviceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_seen_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeviceStatusRead(BaseModel):
    id: int
    name: str
    type: str

    mac_address: Optional[str] = None
    ip_address: Optional[str] = None

    building_id: Optional[int] = None
    floor_id: Optional[int] = None
    location_id: Optional[int] = None

    manufacturer: Optional[str] = None
    model: Optional[str] = None
    shard: Optional[str] = None

    last_seen_at: Optional[datetime] = None
    is_online: bool


class DevicePositionUpdate(BaseModel):
    floor_plan_id: Optional[int] = None
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None

class CameraCreate(DeviceCreate):
    """
    Schema especializado para criação de CÂMERAS.
    - type é sempre "CAMERA" (ignora o que vier do front).
    - building_id e floor_id devem ser informados na rota (validados lá).
    """
    analytics: Optional[list[str]] = None
    type: str = Field("CAMERA", max_length=32)


class CameraUpdate(DeviceUpdate):
    """
    Schema especializado para update de CÂMERAS.
    - type é sempre "CAMERA".
    """
    analytics: Optional[list[str]] = None
    type: Optional[str] = Field("CAMERA", max_length=32)
