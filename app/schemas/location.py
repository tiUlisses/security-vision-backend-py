# app/schemas/location.py
from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel


class PersonCurrentLocation(BaseModel):
    person_id: int
    person_full_name: str

    tag_id: int
    tag_mac_address: str

    device_id: int
    device_name: str
    device_mac_address: Optional[str] = None

    # coordenadas do gateway na planta
    device_pos_x: Optional[float] = None
    device_pos_y: Optional[float] = None

    floor_plan_id: int
    floor_plan_name: str
    floor_plan_image_url: Optional[str] = None

    floor_id: int
    floor_name: str

    building_id: int
    building_name: str

    last_seen_at: datetime


class DeviceCurrentOccupancy(BaseModel):
    device_id: int
    device_name: str
    device_mac_address: Optional[str] = None
    device_pos_x: Optional[float] = None
    device_pos_y: Optional[float] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None
    floor_plan_image_url: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    people: List[PersonCurrentLocation]
