import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai import service
from life_dashboard.ai import coach_service
from life_dashboard.ai import profile_service
from life_dashboard.ai import journal_signal_service
from life_dashboard.ai.models import AiMessageRole
from life_dashboard.ai.schemas import (
    AiSettingsResponse,
    AiSettingsUpdate,
    BootstrapResponse,
    ChatRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    JournalFinishResponse,
    JournalSaveRequest,
    JournalSaveResponse,
    JournalStartRequest,
    JournalStartResponse,
    MessageSearchResponse,
    ProfilePatchRequest,
    ProfileResponse,
    ProfileUpdateListResponse,
    ProfileVersionListResponse,
    ProfileVersionResponse,
    UsageSummaryResponse,
)
from life_dashboard.auth.dependencies import get_current_user, require_ai_enabled
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db

router = APIRouter(prefix="/ai", tags=["ai"])


# ── Coach schemas (inline — small enough not to warrant a separate file) ───────

class CoachDigestResponse(BaseModel):
    id: str
    date: date
    kind: str
    content: str
    tone: str
    created_at: str

    model_config = {"from_attributes": True}


class CoachGenerateRequest(BaseModel):
    kind: str  # "morning" | "evening"
    tone: str = "supportive"
    pinned_project_ids: list[str] = []
    pinned_goal_ids: list[str] = []
    pinned_habit_ids: list[str] = []
    for_date: date | None = None  # defaults to today
    # coach-004: optional free-text "what should the coach focus on today"
    # — surfaces as a "## Focus" section in the user message, before the
    # briefing instructions. Use for things the structured pinned-IDs
    # selectors can't express: "I'm preparing for a hard conversation,
    # help me think through it" or "I want to recover from a rough
    # weekend, go easy".
    focus: str | None = None


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=AiSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> AiSettingsResponse:
    return await service.get_settings(db, current_user.id)


@router.patch("/settings", response_model=AiSettingsResponse)
async def update_settings(
    data: AiSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> AiSettingsResponse:
    # When a NEW api key is supplied (not clearing, not blank), validate it
    # against the relevant provider before persisting. A bad key surfaces
    # immediately rather than failing the next chat request opaquely.
    sent = data.model_fields_set
    if "api_key" in sent and data.api_key and not data.clear_api_key:
        # Determine which provider to test against — prefer the new value if
        # the request is also changing provider, otherwise use the current.
        target_provider_str: str
        if "provider" in sent and data.provider is not None:
            target_provider_str = data.provider
        else:
            current_settings = await service.get_or_create_settings(db, current_user.id)
            target_provider_str = current_settings.provider.value

        if target_provider_str == "anthropic":
            from life_dashboard.ai.provider import AnthropicProvider
            probe = AnthropicProvider(data.api_key.strip())
            ok, err = await probe.validate()
            if not ok:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=err or "Invalid API key.",
                )
        # OpenAI / Ollama validators land here when implemented; for now
        # they pass through unchecked (and the next chat call would fail).

    response = await service.update_settings(db, current_user.id, data)

    # If a key was just (re)added, kick off the bootstrap pass in the
    # background. Silent learning shift: no user click required — by the
    # time the user opens the dashboard, the profile is populated and the
    # coach / chat both speak to them as someone the AI knows.
    if "api_key" in sent and data.api_key and not data.clear_api_key:
        try:
            from life_dashboard.ai.profile_service import (
                get_or_create_memory,
                run_bootstrap_pass,
            )
            memory = await get_or_create_memory(db, current_user.id)
            needs_bootstrap = (
                not (memory.memory_text or "").strip()
                or memory.last_bootstrapped_at is None
            )
            if needs_bootstrap:
                user_settings = await service.get_or_create_settings(db, current_user.id)
                provider = service.get_provider(user_settings)
                if provider is not None:
                    import asyncio
                    asyncio.create_task(
                        _run_bootstrap_background(
                            user_id=current_user.id,
                            household_id=current_user.household_id,
                            display_name=current_user.display_name or current_user.email,
                        )
                    )
        except Exception:
            # Bootstrap is best-effort — never block the settings save.
            pass

    return response


async def _run_bootstrap_background(
    user_id: uuid.UUID,
    household_id: uuid.UUID,
    display_name: str,
) -> None:
    """Background task wrapper for the bootstrap pass.

    Opens its own DB session so the request session is free to return
    immediately. Resolves the provider inside the task — by then the new
    key has already been committed.
    """
    from life_dashboard.core.database import AsyncSessionLocal
    from life_dashboard.ai.profile_service import run_bootstrap_pass

    try:
        async with AsyncSessionLocal() as db:
            user_settings = await service.get_or_create_settings(db, user_id)
            provider = service.get_provider(user_settings)
            if provider is None:
                return
            await run_bootstrap_pass(
                db=db,
                provider=provider,
                user_id=user_id,
                household_id=household_id,
                display_name=display_name,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Background bootstrap pass failed for user %s — ignoring", user_id
        )


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> UsageSummaryResponse:
    """Return token usage totals for the current user.

    this_month_* covers the current calendar month (UTC).
    lifetime_* covers all recorded history.
    by_model breaks down this-month usage per model string.
    """
    return await service.get_usage_summary(db, current_user.id)


# ── Conversations ─────────────────────────────────────────────────────────────

@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ConversationListResponse:
    return await service.list_conversations(db, current_user.id, limit=limit, offset=offset)


@router.get("/conversations/search", response_model=MessageSearchResponse)
async def search_conversations(
    q: str = Query(min_length=2, description="Full-text search query"),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> MessageSearchResponse:
    """Search across all message content in this user's conversation history.

    Uses Postgres full-text search (GIN index). Results are ordered by recency.
    """
    return await service.search_messages(db, current_user.id, q, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ConversationDetailResponse:
    detail = await service.get_conversation_detail(db, conversation_id, current_user.id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return detail


@router.delete("/conversations/{conversation_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> None:
    deleted = await service.delete_conversation(db, conversation_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )


# ── Coach ─────────────────────────────────────────────────────────────────────

@router.get("/coach/digest", response_model=CoachDigestResponse | None)
async def get_coach_digest(
    kind: str = Query(default="morning", description="'morning', 'evening', or 'weekly'"),
    for_date: date | None = Query(default=None, description="Date (YYYY-MM-DD); defaults to today"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> CoachDigestResponse | None:
    """Return the stored coach digest for the given day and kind.

    Returns null (HTTP 200 with null body) when no digest has been generated yet
    for that slot. The frontend uses this to show an empty state with a
    'Generate now' button.
    """
    target_date = for_date or date.today()
    digest = await coach_service.get_digest(db, current_user.id, target_date, kind)
    if digest is None:
        return None
    return CoachDigestResponse(
        id=str(digest.id),
        date=digest.date,
        kind=digest.kind,
        content=digest.content,
        tone=digest.tone,
        created_at=digest.created_at.isoformat(),
    )


@router.post("/coach/digest/generate", response_model=CoachDigestResponse)
async def generate_coach_digest(
    data: CoachGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> CoachDigestResponse:
    """Generate (or regenerate) a coach digest on demand.

    Replaces any existing digest for the same (user, date, kind) slot.
    Called by the widget's 'Generate now' / 'Regenerate' button.
    """
    if data.kind not in ("morning", "evening", "weekly"):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="kind must be 'morning', 'evening', or 'weekly'",
        )

    user_settings = await service.get_or_create_settings(db, current_user.id)
    provider = service.get_provider(user_settings)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI service is not configured. Add an Anthropic API key in Settings, "
                "or ask your household admin to set the system key."
            ),
        )

    target_date = data.for_date or date.today()
    digest = await coach_service.generate_digest(
        db=db,
        provider=provider,
        user_id=current_user.id,
        household_id=current_user.household_id,
        display_name=current_user.display_name or current_user.email,
        for_date=target_date,
        kind=data.kind,
        tone=data.tone,
        pinned_project_ids=data.pinned_project_ids,
        pinned_goal_ids=data.pinned_goal_ids,
        pinned_habit_ids=data.pinned_habit_ids,
        focus=data.focus,
    )

    return CoachDigestResponse(
        id=str(digest.id),
        date=digest.date,
        kind=digest.kind,
        content=digest.content,
        tone=digest.tone,
        created_at=digest.created_at.isoformat(),
    )


@router.get("/coach/tones")
async def get_coach_tones(
    current_user: User = Depends(require_ai_enabled),
) -> dict:
    """Return the available coach tones with labels and descriptions."""
    return {
        key: {"label": val["label"], "description": val["description"]}
        for key, val in coach_service.COACH_TONES.items()
    }


# ── Profile (Phase 1 of AI coach redesign) ────────────────────────────────────

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ProfileResponse:
    """Return the current accepted user profile (empty string if never set)."""
    return await profile_service.get_profile(db, current_user.id)


@router.patch("/profile", response_model=ProfileResponse)
async def patch_profile(
    data: ProfilePatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ProfileResponse:
    """Directly edit the profile content.

    Bypasses the proposed-update workflow — the user is always trusted to
    write their own profile. The AI never writes here directly; it only ever
    proposes via /ai/profile/bootstrap and (in Phase 4) the incremental
    refresher.
    """
    return await profile_service.update_profile(db, current_user.id, data.content_md)


@router.post("/profile/bootstrap", response_model=BootstrapResponse)
async def bootstrap_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> BootstrapResponse:
    """Run the bootstrap pass: read this user's notes, documents, and recent
    behavioural data, ask the AI to draft an initial profile, and create a
    pending UserProfileUpdate for the user to review.

    Idempotent — safe to re-run. Accepting any one update supersedes the rest.
    Returns bootstrap_skipped=True with a reason when there's no usable signal.
    """
    user_settings = await service.get_or_create_settings(db, current_user.id)
    provider = service.get_provider(user_settings)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI service is not configured. Add an Anthropic API key in "
                "Settings → AI, or ask your household admin to set the "
                "system key."
            ),
        )
    return await profile_service.run_bootstrap_pass(
        db=db,
        provider=provider,
        user_id=current_user.id,
        household_id=current_user.household_id,
        display_name=current_user.display_name or current_user.email,
    )


@router.get("/profile/updates", response_model=ProfileUpdateListResponse)
async def list_profile_updates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ProfileUpdateListResponse:
    """Return all pending proposed updates for this user."""
    items = await profile_service.list_pending_updates(db, current_user.id)
    return ProfileUpdateListResponse(items=items)


@router.post("/profile/updates/{update_id}/accept", response_model=ProfileResponse)
async def accept_profile_update(
    update_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ProfileResponse:
    """Accept a pending profile update.

    Copies the proposed content into the profile, marks this update accepted,
    and supersedes any other still-pending updates (they were drafted against
    pre-accept content and would otherwise apply stale changes).
    """
    profile = await profile_service.accept_update(db, current_user.id, update_id)
    if profile is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Update not found or no longer pending",
        )
    return profile


@router.post(
    "/profile/updates/{update_id}/reject",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def reject_profile_update(
    update_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> None:
    """Mark a pending profile update as rejected. Profile content unchanged."""
    ok = await profile_service.reject_update(db, current_user.id, update_id)
    if not ok:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Update not found or no longer pending",
        )


# ── Profile versions (Phase 4 — debug surface, no UI) ─────────────────────────

@router.get("/profile/versions", response_model=ProfileVersionListResponse)
async def list_profile_versions(
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> ProfileVersionListResponse:
    """Return this user's profile version history (newest first).

    Phase 4 debug surface — useful for inspecting how the profile has
    evolved over time or rolling back via direct PATCH /ai/profile if
    something looks wrong. No frontend UI; this is accessible via curl
    or any HTTP client.
    """
    rows = await profile_service.list_profile_versions(
        db, current_user.id, limit=limit
    )
    return ProfileVersionListResponse(
        items=[ProfileVersionResponse.model_validate(r) for r in rows]
    )


# ── Journal signals (Phase 2 of AI coach redesign) ────────────────────────────

class JournalSignalsBackfillResponse(BaseModel):
    """Per-category counts from a backfill run."""
    scanned: int
    extracted: int
    skipped_empty: int
    skipped_current: int
    errors: int


@router.post(
    "/journal-signals/backfill",
    response_model=JournalSignalsBackfillResponse,
)
async def backfill_journal_signals(
    only_outdated_version: bool = Query(
        default=False,
        description=(
            "When true, only re-extract entries whose signal row is at an "
            "older extraction_version. Use this after a prompt revision."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> JournalSignalsBackfillResponse:
    """Run journal signal extraction across every journal entry this user
    has written. Synchronous — the caller is doing this deliberately.

    For the on-save extraction path, see notes service hooks; this endpoint
    is only for first-time backfills and post-prompt-revision re-runs.
    """
    user_settings = await service.get_or_create_settings(db, current_user.id)
    provider = service.get_provider(user_settings)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI service is not configured. Add an Anthropic API key in "
                "Settings → AI, or ask your household admin to set the "
                "system key."
            ),
        )
    counts = await journal_signal_service.backfill_for_user(
        db=db,
        provider=provider,
        user_id=current_user.id,
        household_id=current_user.household_id,
        only_outdated_version=only_outdated_version,
    )
    return JournalSignalsBackfillResponse(**counts)


# ── Journal sessions (journal-001) ────────────────────────────────────────────

@router.post("/journal/start", response_model=JournalStartResponse)
async def start_journal_session(
    data: JournalStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> JournalStartResponse:
    """Start (or resume) a guided journal session anchored to a journal note.

    journal-002: handles three call patterns from the frontend:

    1. Initial mount, no mode:
         POST /ai/journal/start {note_id}
       → returns existing journal conversation if any (is_new=false),
         else creates an EMPTY one (is_new=true, opening_message=None).
         No LLM call. Fast.

    2. Mode pick on an empty conversation:
         POST /ai/journal/start {note_id, mode, local_hour}
       → finds the (just-created) conversation, persists mode, saves
         the canned opener as the first assistant turn, returns the
         opening_message. is_new=false (it was created earlier on mount).

    3. Resume of a session that already has a mode:
         POST /ai/journal/start {note_id} (or {note_id, mode})
       → returns the existing conversation with its stored mode. Any
         mode parameter is ignored — once chosen, the mode is locked.

    Validates:
      - The target note exists and is owned by the current user.
      - It belongs to a collection with kind='journal' (else 400).
    """
    from life_dashboard.ai.models import AiConversation
    from life_dashboard.domains.notes.models import Note
    from life_dashboard.domains.collections.models import Collection

    note = (await db.execute(
        select(Note).where(
            Note.id == data.note_id,
            Note.household_id == current_user.household_id,
            Note.created_by_user_id == current_user.id,
            Note.archived_at.is_(None),
        )
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Journal entry not found.",
        )

    if note.collection_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="That note isn't in a journal collection.",
        )
    kind = (await db.execute(
        select(Collection.kind).where(Collection.id == note.collection_id)
    )).scalar_one_or_none()
    if kind != "journal":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Talk-it-out is only available for journal entries.",
        )

    # Find existing journal conversation for this user+note (per-user
    # scoping enforced by AiConversation.user_id == current_user.id).
    existing = (await db.execute(
        select(AiConversation).where(
            AiConversation.user_id == current_user.id,
            AiConversation.kind == "journal",
            AiConversation.note_id == note.id,
        )
        .order_by(AiConversation.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Helper — true iff this conversation has zero messages of either
    # role. The picker chips should re-appear when an empty conversation
    # gets resumed (e.g. user opened Talk-it-out, closed it without
    # picking a mode, and is now back).
    from life_dashboard.ai.models import AiMessage as _AiMessage

    async def _is_empty(conv_id) -> bool:
        cnt = (await db.execute(
            select(func.count()).select_from(_AiMessage)
            .where(_AiMessage.conversation_id == conv_id)
        )).scalar_one()
        return cnt == 0

    if existing is not None:
        # Case 2 vs 3: does the user want to set a mode on an as-yet
        # unset conversation? Allow exactly that one transition; ignore
        # otherwise (locked after first pick).
        if data.mode is not None and existing.mode is None:
            existing.mode = data.mode
            opener = service.canned_opener_for(data.mode, data.local_hour)
            if opener:
                await service.append_message(
                    db, existing.id, AiMessageRole.assistant, opener
                )
            await db.commit()
            await db.refresh(existing)
            return JournalStartResponse(
                conversation_id=existing.id,
                is_new=False,
                opening_message=opener,
                mode=existing.mode,
                needs_mode_pick=False,
            )
        # Already has a mode (case 3) OR caller didn't supply one (case
        # 1 with existing session) — just return current state. The
        # picker should re-appear iff this conversation is still empty
        # AND no mode has been chosen.
        needs_pick = existing.mode is None and await _is_empty(existing.id)
        return JournalStartResponse(
            conversation_id=existing.id,
            is_new=False,
            opening_message=None,
            mode=existing.mode,
            needs_mode_pick=needs_pick,
        )

    # No existing conversation — create one. If a mode arrived on this
    # call (rare — the frontend usually does mount-then-pick) seed the
    # opener now. Otherwise the conversation is empty and the frontend
    # will follow up with a mode pick.
    conv = AiConversation(
        user_id=current_user.id,
        household_id=current_user.household_id,
        title=f"Journal — {note.title}",
        kind="journal",
        note_id=note.id,
        mode=data.mode,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    opening_message: str | None = None
    if data.mode is not None:
        opener = service.canned_opener_for(data.mode, data.local_hour)
        if opener:
            await service.append_message(
                db, conv.id, AiMessageRole.assistant, opener
            )
            await db.commit()
            opening_message = opener

    return JournalStartResponse(
        conversation_id=conv.id,
        is_new=True,
        opening_message=opening_message,
        mode=conv.mode,
        needs_mode_pick=conv.mode is None,
    )


@router.post(
    "/journal/{conversation_id}/finish",
    response_model=JournalFinishResponse,
)
async def finish_journal_session(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> JournalFinishResponse:
    """Generate a first-person summary of the session, NOT saved yet.

    Frontend renders the result in an editable view; user then calls
    /save with the final content_md.
    """
    from life_dashboard.ai.models import AiConversation

    conv = (await db.execute(
        select(AiConversation).where(
            AiConversation.id == conversation_id,
            AiConversation.user_id == current_user.id,
            AiConversation.kind == "journal",
        )
    )).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Journal session not found.",
        )

    user_settings = await service.get_or_create_settings(db, current_user.id)
    provider = service.get_provider(user_settings)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service is not configured.",
        )

    summary_md, _ = await service.synthesize_journal_summary(
        db=db,
        provider=provider,
        conversation_id=conv.id,
        user_id=current_user.id,
        display_name=current_user.display_name or current_user.email,
    )
    await db.commit()

    if not summary_md:
        # No messages or model returned empty — surface so the UI can show
        # a gentle fallback ('not enough to summarize yet').
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Not enough conversation to summarize yet.",
        )
    return JournalFinishResponse(summary_md=summary_md)


@router.post("/journal/save", response_model=JournalSaveResponse)
async def save_journal_session(
    data: JournalSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> JournalSaveResponse:
    """Persist the journal session as appended content on the target note.

    Layout of the saved entry:
      <existing content (if any)>
      <---  (divider only when existing content is non-empty)>
      <summary content>
      <---  (only when include_transcript=true)>
      ## Conversation transcript
      <transcript>

    The journal note's existing content is PRESERVED; this endpoint
    APPENDS rather than replacing.
    """
    from life_dashboard.ai.models import AiConversation
    from life_dashboard.domains.notes.models import Note
    from life_dashboard.domains.notes.service import update_note as notes_update_note
    from life_dashboard.domains.notes.schemas import NoteUpdate

    conv = (await db.execute(
        select(AiConversation).where(
            AiConversation.id == data.conversation_id,
            AiConversation.user_id == current_user.id,
            AiConversation.kind == "journal",
        )
    )).scalar_one_or_none()
    if conv is None or conv.note_id is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Journal session not found.",
        )

    note = (await db.execute(
        select(Note).where(
            Note.id == conv.note_id,
            Note.household_id == current_user.household_id,
        )
    )).scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Target journal note no longer exists.",
        )

    # Assemble final content: existing + (divider if existing) + summary
    # + (transcript section if requested).
    existing = (note.content_md or "").rstrip()
    summary = data.content_md.strip()

    parts: list[str] = []
    if existing:
        parts += [existing, "", "---", ""]
    parts.append(summary)

    if data.include_transcript:
        # Re-format the transcript locally from the saved messages — no
        # need to re-run the model (synthesize_journal_summary would, but
        # we already have the summary the user just edited). This is the
        # working artifact, not the summary.
        from life_dashboard.ai.models import AiMessageRole
        recent = await service.get_recent_messages(db, conv.id, limit=200)
        role_label = {
            AiMessageRole.user: "You",
            AiMessageRole.assistant: "Coach",
        }
        transcript_lines: list[str] = []
        for msg in recent:
            label = role_label.get(msg.role, str(msg.role.value).title())
            transcript_lines.append(f"**{label}:** {msg.content.strip()}")
            transcript_lines.append("")
        transcript_md = "\n".join(transcript_lines).strip()
        if transcript_md:
            parts += ["", "---", "", "## Conversation transcript", "", transcript_md]

    final_content = "\n".join(parts)

    # Update the note. Goes through the normal notes service path so
    # backlinks resolve + the existing maybe_propose_from_notes /
    # maybe_extract_signals hooks fire automatically.
    await notes_update_note(
        db,
        note_id=note.id,
        household_id=current_user.household_id,
        data=NoteUpdate(content_md=final_content),
    )
    return JournalSaveResponse(note_id=note.id)


# ── Chat (streaming) ──────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_ai_enabled),
) -> StreamingResponse:
    """Send a message and receive a streaming response.

    If conversation_id is omitted, a new conversation is created automatically
    and its ID is included in the final `done` SSE event.

    SSE event shapes:
      data: {"type": "delta",  "content": "<text>"}
      data: {"type": "done",   "conversation_id": "<uuid>", "message_id": "<uuid>"}
      data: {"type": "error",  "message": "<user-facing text>"}
    """
    # 1. Load or create the conversation.
    if data.conversation_id is not None:
        conv = await service.get_conversation(db, data.conversation_id, current_user.id)
        if conv is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
    else:
        conv = await service.create_conversation(
            db, current_user.id, current_user.household_id, data.content
        )

    # 2. Resolve provider — fail fast before touching the DB further.
    user_settings = await service.get_or_create_settings(db, current_user.id)
    provider = service.get_provider(user_settings)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "AI service is not configured. Add an Anthropic API key in Settings, "
                "or ask your household admin to set the system key."
            ),
        )

    # 3. Apply retention policy (lazy cleanup — best-effort, non-blocking).
    if user_settings.retention_days is not None:
        try:
            await service.apply_retention_policy(
                db, current_user.id, user_settings.retention_days
            )
        except Exception:
            pass  # Retention failure must never block a chat turn

    # 4. Save the user message.
    await service.append_message(db, conv.id, AiMessageRole.user, data.content)
    await db.commit()

    # 5. Assemble context (system prompt + memory + recent turns).
    memory = await service.get_or_create_memory(db, current_user.id)
    system, messages = await service.build_chat_context(db, conv.id, current_user, memory)

    # 5b. Context-aware chat (chat-001): if the client included a
    # current-resource ref, resolve it and append the block to the system
    # prompt. Failures are silent — the chat must never break because of
    # a stale or unauthorised ref.
    if data.context is not None:
        try:
            from life_dashboard.ai.chat_context_resolver import resolve_chat_context
            ctx_block = await resolve_chat_context(
                db, current_user.id, current_user.household_id, data.context
            )
            if ctx_block:
                system = system + "\n\n" + ctx_block
        except Exception:
            pass

    # 6. Return the streaming response.
    # journal-001: for journal-kind conversations, restrict the tool set to
    # update_profile only — this is a working space, not a task interface.
    journal_tools: list[dict] | None = None
    if getattr(conv, "kind", "chat") == "journal":
        from life_dashboard.ai.tools import TOOL_DEFINITIONS as _TOOLS
        journal_tools = [t for t in _TOOLS if t["name"] == "update_profile"]

    return StreamingResponse(
        service.generate_stream(
            db=db,
            provider=provider,
            conversation_id=conv.id,
            user_id=current_user.id,
            household_id=current_user.household_id,
            display_name=current_user.display_name or current_user.email,
            system=system,
            messages=messages,
            tools=journal_tools,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable Nginx/Caddy response buffering so chunks reach the client
            # as they are generated rather than in one batched flush.
            "X-Accel-Buffering": "no",
        },
    )
