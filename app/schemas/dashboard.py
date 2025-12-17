from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total_people: int
    total_tags: int
    total_gateways: int
    gateways_online: int
    gateways_offline: int
    active_alert_rules: int
    recent_alerts_24h: int
