from app.api.routes import buildings
from app.api.routes import floors
from app.api.routes import floor_plans
from app.api.routes import devices
from app.api.routes import people
from app.api.routes import tags
from app.api.routes import collection_logs
from app.api.routes import dashboard
from app.api.routes import person_groups
from app.api.routes import alert_rules
from app.api.routes import webhooks
from app.api.routes import alert_events
from app.api.routes import positions
from app.api.routes import reports
from app.api.routes import auth
from app.api.routes import incidents
from app.api.routes import chatwoot_webhooks as integrations_chatwoot
from app.api.routes import support_groups
from app.api.routes import users
from app.api.routes import locations
# testing 
__all__ = [
    "buildings",
    "floors",
    "floor_plans",
    "devices",
    "people",
    "tags",
    "collection_logs",
    "dashboard",
    "person_groups",
    "alert_rules",
    "webhooks",
    "alert_events",
    "positions",
    "reports",
    "auth",
    "incidents",
    "integrations_chatwoot",
    "support_groups",
    "users",
    "locations",
]
