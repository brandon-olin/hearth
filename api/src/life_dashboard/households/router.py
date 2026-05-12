import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import HouseholdMembership, User
from life_dashboard.core.database import get_db

router = APIRouter(prefix="/households", tags=["households"])


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    display_name: str | None
    email: str
    role: str
    joined_at: datetime


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MemberResponse]:
    """Return all active members of the current user's household."""
    result = await db.execute(
        select(User, HouseholdMembership.role, HouseholdMembership.joined_at)
        .join(HouseholdMembership, User.id == HouseholdMembership.user_id)
        .where(
            HouseholdMembership.household_id == current_user.household_id,
            User.is_active == True,  # noqa: E712
        )
        .order_by(HouseholdMembership.joined_at.asc())
    )
    return [
        MemberResponse(
            user_id=user.id,
            display_name=user.display_name,
            email=user.email,
            role=role.value,
            joined_at=joined_at,
        )
        for user, role, joined_at in result.all()
    ]
