"""
Household-agent pseudo-member provisioning (mcp-002 / plans/open-hearth/mcp-server.md).

Shared devices — the kitchen speaker, a household OpenClaw instance — are not a
person, so their writes are attributed to a **household-agent pseudo-member**: a
real ``User`` row carrying membership role ``agent`` (rank 1, viewer-level). This
gives honest audit attribution ("kitchen speaker added milk"), survives any
human member's deactivation, and never impersonates a person.

Why a real user row rather than a magic sentinel: the whole permission stack —
``apply_visibility_filter``, ``load_household_permissions``, the PAT member
ceiling — already keys off a membership role, so the agent gets shared-scope
reads/writes for free and is refused personal or sensitive scope automatically.
The account has an unusable password (never logs in; only its PATs authenticate)
and is deliberately never made a todo assignee.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.auth.models import HouseholdMembership, MembershipRole, User

#: Deterministic, per-household email so provisioning is idempotent — a second
#: call finds the existing agent rather than minting a duplicate. The domain is
#: reserved/unroutable so the address can never collide with a real member.
_AGENT_EMAIL = "household-agent+{household_id}@agents.hearth.local"

#: An argon2 hash is always a long "$argon2..." string, so a literal "!" can
#: never match any password — the account is unauthenticatable by password and
#: reachable only through its scoped PATs.
_UNUSABLE_PASSWORD_HASH = "!"

AGENT_DISPLAY_NAME = "Household Agent"


async def get_or_create_household_agent(
    db: AsyncSession, household_id: uuid.UUID
) -> User:
    """Return the household's agent pseudo-member, creating it on first use.

    Idempotent: keyed on the deterministic per-household email, so concurrent or
    repeated provisioning converges on one agent row. Commits.
    """
    email = _AGENT_EMAIL.format(household_id=household_id)

    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=_UNUSABLE_PASSWORD_HASH,
            display_name=AGENT_DISPLAY_NAME,
            is_active=True,
        )
        db.add(user)
        await db.flush()

    membership = (
        await db.execute(
            select(HouseholdMembership).where(HouseholdMembership.user_id == user.id)
        )
    ).scalar_one_or_none()
    if membership is None:
        db.add(
            HouseholdMembership(
                household_id=household_id,
                user_id=user.id,
                role=MembershipRole.agent,
            )
        )

    await db.commit()
    await db.refresh(user)
    return user
