# app/schemas/location.py
from datetime import datetime, time
from typing import Optional, List

from pydantic import BaseModel, Field


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


class LocationBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "ACTIVE"


class LocationCreate(LocationBase):
    floor_ids: List[int] = Field(default_factory=list)


class LocationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    floor_ids: Optional[List[int]] = None


class LocationRead(LocationBase):
    id: int
    floor_ids: List[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LocationRuleBase(BaseModel):
    capacity: Optional[int] = None
    avaliable_days: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: str = "ACTIVE"
    validate: bool = True


class LocationRuleCreate(LocationRuleBase):
    location_id: int


class LocationRuleUpdate(BaseModel):
    capacity: Optional[int] = None
    avaliable_days: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    status: Optional[str] = None
    validate: Optional[bool] = None


class LocationRuleRead(LocationRuleBase):
    id: int
    location_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
