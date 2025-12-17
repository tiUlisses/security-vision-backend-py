# app/models/incident_assignee.py (ou junto no incident.py)

from sqlalchemy import Table, Column, Integer, ForeignKey
from app.db.base_class import Base


incident_assignees = Table(
    "incident_assignees",
    Base.metadata,
    Column(
        "incident_id",
        ForeignKey("incidents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)