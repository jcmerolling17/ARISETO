from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User
from app.models.enums import AccountStatus, CropSeason, UserRole
from app.schemas.admin import AdminUserItem, UserCounts, UserStatusResponse, UserStatusUpdate
from app.schemas.alert_rule import AlertRuleItem, AlertRuleUpdate
from app.schemas.report import CooperativeReport
from app.services import admin_service, alert_rule_service, report_service

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[AdminUserItem])
def list_users(
    status: AccountStatus | None = None,
    deletion_requested: bool | None = None,
    role: UserRole | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserItem]:
    """Accounts, newest first, optionally filtered by status, role, deletion request (true:
    not yet processed), and q (name, mobile or member number, ignoring case).
    Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin.
    """
    return admin_service.list_users(
        db,
        status=status,
        deletion_requested=deletion_requested,
        role=role,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get("/users/counts", response_model=UserCounts)
def user_counts(_admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> UserCounts:
    """Member accounts in each account_status, and unprocessed deletion requests.
    Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin.
    """
    return admin_service.counts(db)


@router.post("/users/{user_id}/process-deletion", response_model=UserStatusResponse)
def process_deletion(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserStatusResponse:
    """Process a member's deletion request: deactivate the account, end its sessions and
    remove its personal details; farm records stay. Processing again changes nothing.
    Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin; 404 user_not_found;
    409 no_deletion_request, cannot_deactivate_self, last_active_admin.
    """
    user = admin_service.process_deletion(db, admin, user_id)
    return UserStatusResponse(user_id=user.user_id, account_status=user.account_status)


@router.get("/reports/cooperative", response_model=CooperativeReport)
def cooperative_report(
    season: CropSeason | None = None,
    season_year: int | None = Query(None, ge=1, le=9999),
    municipality: str | None = None,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CooperativeReport:
    """Crop health and yield across MPMPC farms for one season (DFD 7.6), computed on request
    from the same per-farm figures as the farm report; no names or contact details.
    Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin;
    422 season_incomplete, unknown_municipality.
    """
    return report_service.cooperative_report(db, season, season_year, municipality)


@router.patch("/users/{user_id}/status", response_model=UserStatusResponse)
def update_user_status(
    user_id: int,
    data: UserStatusUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserStatusResponse:
    """Approve a pending account ('active') or deactivate one. Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin; 404 user_not_found;
    409 cannot_deactivate_self, last_active_admin.
    """
    user = admin_service.set_account_status(db, admin, user_id, data.account_status)
    return UserStatusResponse(user_id=user.user_id, account_status=user.account_status)


@router.get("/alert-rules", response_model=list[AlertRuleItem])
def list_alert_rules(
    _admin: User = Depends(require_admin), db: Session = Depends(get_db)
) -> list[AlertRuleItem]:
    """The weather alert rules in rule_id order. Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin.
    """
    return alert_rule_service.list_rules(db)


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleItem)
def update_alert_rule(
    rule_id: int,
    data: AlertRuleUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AlertRuleItem:
    """Change a rule's is_active, threshold or message_template ({value} and {hours} only).
    Applies from the next evaluation. Cooperative administrators only.

    Errors: 401 not_authenticated; 403 account_deactivated, not_admin; 404 rule_not_found;
    422 invalid_template.
    """
    return alert_rule_service.update_rule(db, rule_id, data)
