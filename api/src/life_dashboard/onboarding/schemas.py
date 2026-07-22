from pydantic import BaseModel, Field


class DemoDataStatus(BaseModel):
    """What the dashboard banner needs to decide whether to show itself."""

    #: True when this household still holds sample data the seeder created.
    present: bool
    #: Manifest counts by entity type, e.g. {"todo": 5, "habit": 3}. Empty when
    #: nothing is seeded. Entity types with a zero count are omitted.
    counts: dict[str, int] = Field(default_factory=dict)


class SeedDemoDataResponse(BaseModel):
    """Result of asking for sample data.

    ``seeded`` False is a normal, successful outcome — the household already
    had content, or already has sample data. ``reason`` says which, so the
    caller (and an agent) can tell "nothing to do" from "something went wrong".
    """

    seeded: bool
    #: One of: "already_seeded", "household_has_data", or None when seeded=True.
    reason: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class ClearDemoDataResponse(BaseModel):
    """Result of clearing sample data. Idempotent: a second call returns 200
    with ``cleared`` False and all-zero counts rather than erroring."""

    cleared: bool
    #: Rows actually deleted, by entity type. Omits zero counts.
    counts: dict[str, int] = Field(default_factory=dict)
    #: Entity types deliberately left in place because a record the *user*
    #: created still depends on them (today: a budget account that has picked up
    #: real transactions). Empty in the common case.
    retained: dict[str, int] = Field(default_factory=dict)


class OnboardingStatusResponse(BaseModel):
    """Per-member onboarding state, plus the household context the wizard needs.

    ``wizard_completed`` is read from ``users.preferences`` and is per member,
    never per household — someone who joins an established household later has
    not been onboarded and should still see the wizard.
    """

    wizard_completed: bool
    #: Module ids the member picked in the wizard ("finance", "habits", …).
    #: Empty when the wizard has not run or the member skipped the question.
    modules: list[str] = Field(default_factory=list)
    #: Ids of the first-visit hints this member has dismissed (onboarding-003).
    #: Per member, like the wizard flag — dismissing the budget hint does not
    #: take it away from a partner who has never opened the page.
    dismissed_hints: list[str] = Field(default_factory=list)
    #: Every hint id the client may show, mapped to the page it belongs to.
    #: Sent so a client (or an agent) can enumerate hints without hard-coding
    #: the list.
    available_hints: dict[str, str] = Field(default_factory=dict)
    #: True when the household holds any content the user actually created —
    #: sample data does not count. This is the guard that stops the seeder
    #: writing over someone's work.
    household_has_data: bool
    demo_data: DemoDataStatus


class DismissHintRequest(BaseModel):
    """Ask to stop showing one first-visit hint to the calling member."""

    #: One of the ids in ``OnboardingStatusResponse.available_hints``.
    hint_id: str


class HintStateResponse(BaseModel):
    """The member's hint state after a dismiss or a reset.

    Both operations return the full list rather than an acknowledgement, so a
    client never has to re-read to find out where it stands.
    """

    dismissed_hints: list[str] = Field(default_factory=list)
    available_hints: dict[str, str] = Field(default_factory=dict)
