from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.models.enums import CropSeason
from app.schemas.expense import (
    ExpenseCategoryOut,
    ExpenseCreate,
    ExpenseCreated,
    ExpenseItem,
    SeasonSummary,
)
from app.services import expense_service

router = APIRouter(tags=["expenses"])


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
def list_categories(
    _user: User = Depends(require_active_user), db: Session = Depends(get_db)
) -> list[ExpenseCategoryOut]:
    """The seven expense categories in their documented order."""
    return expense_service.list_categories(db)


@router.get("/farms/{farm_id}/expenses", response_model=list[ExpenseItem])
def list_expenses(
    farm_id: int,
    season: CropSeason | None = None,
    season_year: int | None = Query(None, ge=1, le=9999),
    field_id: int | None = None,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> list[ExpenseItem]:
    """A season's expenses, newest first; without season and season_year, the current
    season by today's Philippine date. Farm members only.

    Errors: 403 not_farm_member; 422 season_incomplete, field_not_in_farm.
    """
    where = expense_service.resolve_filter(db, user, farm_id, season, season_year, field_id)
    return expense_service.list_expenses(db, user, where)


@router.post(
    "/farms/{farm_id}/expenses",
    status_code=status.HTTP_201_CREATED,
    response_model=ExpenseCreated,
)
def create_expense(
    farm_id: int,
    data: ExpenseCreate,
    response: Response,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> ExpenseCreated:
    """Record an expense for a field's crop cycle or the whole farm. A client_uuid already
    saved by the caller on this farm returns that expense with 200 instead of a duplicate.

    Errors: 403 not_farm_member; 409 client_uuid_taken; 422 category_not_found,
    cycle_not_in_farm, season_required, season_mismatch, unit_required, quantity_required,
    expense_date_in_future.
    """
    created, is_new = expense_service.create_expense(db, user, farm_id, data)
    if not is_new:
        response.status_code = status.HTTP_200_OK
    return created


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    expense_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> Response:
    """Remove an expense: the member who recorded it, or the farm owner.

    Errors: 403 not_allowed; 404 expense_not_found.
    """
    expense_service.delete_expense(db, user, expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/farms/{farm_id}/summary", response_model=SeasonSummary)
def season_summary(
    farm_id: int,
    season: CropSeason | None = None,
    season_year: int | None = Query(None, ge=1, le=9999),
    field_id: int | None = None,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> SeasonSummary:
    """Season totals: expenses by category, gross income, and net profit (computed on
    request). With field_id, whole-farm expenses are left out.

    Errors: 403 not_farm_member; 422 season_incomplete, field_not_in_farm.
    """
    where = expense_service.resolve_filter(db, user, farm_id, season, season_year, field_id)
    return expense_service.summary(db, where)
