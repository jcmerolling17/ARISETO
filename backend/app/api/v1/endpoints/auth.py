from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """Create a member account; it stays 'pending' until a coop_admin approves it.

    Errors: 409 mobile_taken, email_taken, member_no_taken; 422 barangay_municipality_mismatch.
    """
    user = auth_service.register_member(db, data)
    return RegisterResponse(user_id=user.user_id, account_status=user.account_status)


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Sign in with mobile_no or email.

    Errors: 401 invalid_credentials; 403 account_pending, account_deactivated.
    """
    return auth_service.login(db, data)
