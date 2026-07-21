import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class AuditSource(str, Enum):
    """Where an audited write originated.

    web    — a logged-in browser session (token_id is NULL).
    mcp    — an MCP tool call authenticated by a PAT.
    voice  — an Alexa (or other voice-platform) intent authenticated by a PAT.
    script — a maintenance/seed script authenticated by a PAT.
    system — the API itself acting with no human or token behind it, e.g. the
             webhook worker auto-disabling a subscription whose endpoint died.
             Both attribution columns are NULL for these.
    """
    web = "web"
    mcp = "mcp"
    voice = "voice"
    script = "script"
    system = "system"


class AuditLogResponse(BaseModel):
    """A single audit row, for the eventual Activity page / audit queries."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    token_id: uuid.UUID | None
    source: str
    action: str
    entity_type: str
    entity_id: str | None
    payload: dict | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    limit: int
    offset: int
