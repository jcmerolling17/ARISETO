from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.core.errors import AppError
from app.db.session import get_db
from app.models import User
from app.schemas.chat import ChatExchange, ChatMessageItem, ChatRequest, ChatSessionItem
from app.services import chat_model, chat_service
from app.services.chat_model import Predictor

router = APIRouter(tags=["chat"])


def get_chat_predictor() -> Predictor:
    """The loaded intent model; 503 model_unavailable when none is loaded."""
    predictor = chat_model.current().predictor
    if predictor is None:
        raise AppError(503, "model_unavailable")
    return predictor


@router.post("/chat/messages", status_code=status.HTTP_201_CREATED, response_model=ChatExchange)
def send_message(
    data: ChatRequest,
    user: User = Depends(require_active_user),
    predictor: Predictor = Depends(get_chat_predictor),
    db: Session = Depends(get_db),
) -> ChatExchange:
    """Ask the chatbot. Leave out session_id to start a new conversation; farm_id is the farm
    used for the farm-data answers (the caller's only farm when left out).

    Errors: 403 not_farm_member; 404 session_not_found; 422 message_empty, message_too_long;
    503 model_unavailable (nothing is saved).
    """
    return chat_service.send_message(db, user, predictor, data)


@router.get("/chat/sessions", response_model=list[ChatSessionItem])
def list_sessions(
    limit: int = Query(10, ge=1, le=50),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[ChatSessionItem]:
    """The caller's conversations, latest activity first."""
    return chat_service.list_sessions(db, user, limit)


@router.get("/chat/sessions/{session_id}/messages", response_model=list[ChatMessageItem])
def list_messages(
    session_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[ChatMessageItem]:
    """A conversation's messages, oldest first.

    Errors: 404 session_not_found, also for another user's session.
    """
    return chat_service.list_messages(db, user, session_id, limit, offset)
