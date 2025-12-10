# app/schemas/gateway_report.py
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class GatewayUsageDeviceSummary(BaseModel):
    device_id: int
    device_name: Optional[str] = None
    device_mac_address: Optional[str] = None

    building_id: Optional[int] = None
    building_name: Optional[str] = None

    floor_id: Optional[int] = None
    floor_name: Optional[str] = None

    floor_plan_id: Optional[int] = None
    floor_plan_name: Optional[str] = None

    total_dwell_seconds: int
    sessions_count: int
    unique_people_count: int

    first_session_at: Optional[datetime] = None
    last_session_at: Optional[datetime] = None


class GatewayUsageSummary(BaseModel):
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    total_sessions: int
    total_dwell_seconds: int
    total_devices: int

    gateways: List[GatewayUsageDeviceSummary]
    # atalho pro "campeão"
    top_device_id: Optional[int] = None


class GatewayTimeOfDayBucket(BaseModel):
    hour: int  # 0..23
    total_dwell_seconds: int
    sessions_count: int
    unique_people_count: int


class GatewayTimeOfDayDistribution(BaseModel):
    device_id: int
    device_name: Optional[str] = None

    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None

    buckets: List[GatewayTimeOfDayBucket]
