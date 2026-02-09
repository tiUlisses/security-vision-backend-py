from app.db.base_class import Base  # noqa: F401

# Importa explicitamente todos os models para registrar as tabelas no Base.metadata.
from app.models.alert_event import AlertEvent  # noqa: F401
from app.models.alert_rule import AlertRule  # noqa: F401
from app.models.building import Building  # noqa: F401
from app.models.camera_group import CameraGroup, CameraGroupDevice  # noqa: F401
from app.models.collection_log import CollectionLog  # noqa: F401
from app.models.device import Device  # noqa: F401
from app.models.device_event import DeviceEvent  # noqa: F401
from app.models.device_topic import DeviceTopic  # noqa: F401
from app.models.device_user import DeviceUser  # noqa: F401
from app.models.floor import Floor  # noqa: F401
from app.models.floor_plan import FloorPlan  # noqa: F401
from app.models.incident import Incident  # noqa: F401
from app.models.incident_assignee import incident_assignees  # noqa: F401
from app.models.incident_attachment import IncidentAttachment  # noqa: F401
from app.models.incident_message import IncidentMessage  # noqa: F401
from app.models.incident_rule import IncidentRule  # noqa: F401
from app.models.location import Location, LocationRule, location_floors  # noqa: F401
from app.models.person import Person  # noqa: F401
from app.models.person_group import PersonGroup, person_group_memberships  # noqa: F401
from app.models.presence_daily_usage import PresenceDailyUsage  # noqa: F401
from app.models.presence_session import PresenceSession  # noqa: F401
from app.models.presence_transition import PresenceTransition  # noqa: F401
from app.models.support_group import SupportGroup  # noqa: F401
from app.models.tag import Tag  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.webhook_subscription import WebhookSubscription  # noqa: F401
