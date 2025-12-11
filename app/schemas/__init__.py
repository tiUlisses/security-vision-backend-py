# app/schemas/__init__.py
from app.schemas.building import (
    BuildingBase,
    BuildingCreate,
    BuildingUpdate,
    BuildingRead,
)
from app.schemas.floor import (
    FloorBase,
    FloorCreate,
    FloorUpdate,
    FloorRead,
)
from .incident_message import (
    IncidentMessageBase,
    IncidentMessageCreate,
    IncidentMessageRead,
)
from app.schemas.floor_plan import (
    FloorPlanBase,
    FloorPlanCreate,
    FloorPlanUpdate,
    FloorPlanRead,
)
from app.schemas.device import (
  DeviceBase,
    DeviceCreate,
    DeviceUpdate,
    DeviceRead,
    DeviceStatusRead,
    DevicePositionUpdate,
    CameraCreate,
    CameraUpdate,
)
from app.schemas.person import (
    PersonBase,
    PersonCreate,
    PersonUpdate,
    PersonRead,
)

from app.schemas.device_topic import (
    DeviceTopicRead,        # 👈 ADICIONAR
    DeviceTopicCreate,
    DeviceTopicUpdate,

)

from app.schemas.tag import (
    TagBase,
    TagCreate,
    TagUpdate,
    TagRead,
)
from app.schemas.collection_log import (
    CollectionLogBase,
    CollectionLogCreate,
    CollectionLogUpdate,
    CollectionLogRead,
)

from app.schemas.location import PersonCurrentLocation, DeviceCurrentOccupancy
from app.schemas.device_event import DeviceEventRead, DeviceEventCreate
from app.schemas.alert_event import AlertEventCreate, AlertEventUpdate, AlertEventRead

from .person_report import (
    PersonDwellByDevice,
    PersonPresenceSummary,
    PersonTimelineSession,
    PersonAlertByType,
    PersonAlertByDevice,
    PersonAlertEvent,
    PersonAlertsReport,
    PersonTimeDistributionBucket,
    PersonTimeDistributionCalendar,
    PersonTimeOfDayBucket,
    PersonTimeOfDayDistribution,
    PersonDayOfWeekBucket,
    PersonDayOfWeekDistribution,
    GroupPersonDwellSummary,
    GroupDwellByDevice,
    PersonGroupPresenceSummary,
    PersonGroupAlertsReport,
    PersonHourByGatewayBucket,
    PersonTimeOfDayByGateway,
)

from .person_group import (
    PersonGroupBase,
    PersonGroupCreate,
    PersonGroupUpdate,
    PersonGroupRead,
    PersonGroupWithMembers,
    PersonGroupMembersUpdate,
)

from .gateway_report import (
    GatewayUsageDeviceSummary,
    GatewayUsageSummary,
    GatewayTimeOfDayBucket,
    GatewayTimeOfDayDistribution,
)

from .incident import (
    IncidentBase,
    IncidentCreate,
    IncidentUpdate,
    IncidentRead,
    IncidentFromDeviceEventCreate,
)

from .incident_rule import (
    IncidentRuleBase,
    IncidentRuleCreate,
    IncidentRuleUpdate,
    IncidentRuleRead,

)
from .camera_group import (
    CameraGroupCreate,
    CameraGroupRead,
    CameraGroupUpdate,
)

__all__ = [
    "BuildingBase",
    "BuildingCreate",
    "BuildingUpdate",
    "BuildingRead",
    "FloorBase",
    "FloorCreate",
    "FloorUpdate",
    "FloorRead",
    "FloorPlanBase",
    "FloorPlanCreate",
    "FloorPlanUpdate",
    "FloorPlanRead",
    "DeviceBase",
    "DeviceCreate",
    "DeviceUpdate",
    "DeviceRead",
    "PersonBase",
    "PersonCreate",
    "PersonUpdate",
    "PersonRead",
    "TagBase",
    "TagCreate",
    "TagUpdate",
    "TagRead",
    "CollectionLogBase",
    "CollectionLogCreate",
    "CollectionLogUpdate",
    "CollectionLogRead",
    "PersonCurrentLocation",
    "DeviceCurrentOccupancy",
    "DeviceStatusRead",
    "DevicePositionUpdate",
    "AlertEventRead",
    "AlertEventCreate",
    "AlertEventUpdate",
    "PersonDwellByDevice",
    "PersonPresenceSummary",
    "PersonTimelineSession",
    "PersonAlertByDevice",
    "PersonAlertByType",
    "PersonAlertEvent",
    "PersonAlertsReport",
    "PersonTimeDistributionBucket",
    "PersonTimeDistributionCalendar",
    "PersonTimeOfDayBucket",
    "PersonTimeOfDayDistribution",
    "PersonDayOfWeekBucket",
    "PersonDayOfWeekDistribution",
    "PersonGroupBase",
    "PersonGroupCreate",
    "PersonGroupUpdate",
    "PersonGroupRead",
    "PersonGroupWithMembers",
    "PersonGroupMembersUpdate",
    "GroupPersonDwellSummary",
    "GroupDwellByDevice",
    "PersonGroupPresenceSummary",
    "PersonGroupAlertsReport",
    "GatewayUsageDeviceSummary",
    "GatewayUsageSummary",
    "GatewayTimeOfDayBucket",
    "GatewayTimeOfDayDistribution",
    "PersonHourByGatewayBucket",
    "PersonTimeOfDayByGateway",
    "CameraCreate",
    "CameraUpdate",
    "DeviceTopicRead",      # 👈 ADICIONAR
    "DeviceTopicCreate",
    "DeviceTopicUpdate",
    "DeviceEventRead",
    "AlertEventCreate",
    "AlertEventUpdate",
    "IncidentBase",
    "IncidentCreate",
    "IncidentUpdate",
    "IncidentRead",
    "IncidentFromDeviceEventCreate",
    "IncidentMessageBase",
    "IncidentMessageCreate",
    "IncidentMessageRead",
    "IncidentRuleBase",
    "IncidentRuleCreate",
    "IncidentRuleUpdate",
    "IncidentRuleRead",
    "DeviceEventCreate",
    "DeviceEventRead",
    "CameraGroupCreate",
    "CameraGroupRead",
    "CameraGroupUpdate",
    

]
