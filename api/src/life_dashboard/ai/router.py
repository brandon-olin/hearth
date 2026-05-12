import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.ai import service
from life_dashboard.ai.models import AiMessageRole
from life_dashboard.ai.schemas import (
    AiSettingsResponse,
    AiSettingsUpdate,
    ChatRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    MessageSearchResponse,
    UsageSummaryResponse,
)
from life_dashboard.auth.dependencies import get_current_user
from life_dashboard.auth.models import User
from life_dashboard.core.database import get_db

router = APIRouter(prefix="/ai", tags=["ai"])


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings", response_model=AiSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiSettingsResponse:
    return await service.get_settings(db, current_user.id)


@router.patch("/settings", response_model=AiSettingsResponse)
async def update_settings(
    data: AiSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AiSettingsResponse:
    return await service.update_settings(db, current_user.id, data)


# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get("/usage", response_model=UsageSummaryResponse)
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    return await service.list_conversations(db, current_user.id, limit=limit, offset=offset)


@router.get("/conversations/search", response_model=MessageSearchResponse)
async def search_conversations(
    q: str = Query(min_length=2, description="Full-text search query"),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageSearchResponse:
    """Search across all message content in this user's conversation history.

    Uses Postgres full-text search (GIN index). Results are ordered by recency.
    """
    return await service.search_messages(db, current_user.id, q, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
) -> None:
    deleted = await service.delete_conversation(db, conversation_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )


# ── Chat (streaming) ──────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    data: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # 6. Return the streaming response.
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
