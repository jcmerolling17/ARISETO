"""Expenses and the seasonal summary (Section 6). An expense belongs to one field's crop cycle
or to the whole farm for a season; totals and net profit are per season, computed on request.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.seasons import cycle_season_year, philippine_today, season_of
from app.models import (
    CropCycle,
    Expense,
    ExpenseCategory,
    FarmField,
    HarvestRecord,
    User,
)
from app.models.enums import CropSeason, FarmRole
from app.schemas.expense import (
    CategoryAmount,
    ExpenseCategoryOut,
    ExpenseCreate,
    ExpenseCreated,
    ExpenseItem,
    SeasonSummary,
)
from app.services.farm_service import farm_role_of, require_farm_member

_CLIENT_UUID_CONSTRAINT = "uq_expense_client_uuid"


@dataclass(frozen=True)
class SeasonFilter:
    """A farm, the caller's role on it, one season, and optionally one of its fields."""

    farm_id: int
    role: FarmRole
    season: CropSeason
    season_year: int
    field_id: int | None


def list_categories(db: Session) -> list[ExpenseCategoryOut]:
    rows = db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.category_id))
    return [
        ExpenseCategoryOut(category_id=c.category_id, category_name=c.category_name) for c in rows
    ]


def resolve_filter(
    db: Session,
    user: User,
    farm_id: int,
    season: CropSeason | None,
    season_year: int | None,
    field_id: int | None,
) -> SeasonFilter:
    """The filters shared by the expense list, harvest list, and summary. Without season
    and season_year, the current season by today's Philippine date.

    Errors: 403 not_farm_member; 422 season_incomplete, field_not_in_farm.
    """
    role = require_farm_member(db, user, farm_id)
    if (season is None) != (season_year is None):
        raise AppError(422, "season_incomplete")
    if season is None:
        season, season_year = season_of(philippine_today())
    if field_id is not None:
        field_farm = db.scalar(select(FarmField.farm_id).where(FarmField.field_id == field_id))
        if field_farm != farm_id:
            raise AppError(422, "field_not_in_farm")
    return SeasonFilter(farm_id, role, season, season_year, field_id)


def season_cycle_ids(db: Session, where: SeasonFilter) -> list[int]:
    """The farm's crop cycles (on the chosen field, if any) that belong to the season."""
    query = (
        select(CropCycle)
        .join(FarmField, FarmField.field_id == CropCycle.field_id)
        .where(FarmField.farm_id == where.farm_id, CropCycle.season == where.season)
    )
    if where.field_id is not None:
        query = query.where(CropCycle.field_id == where.field_id)
    return [
        cycle.cycle_id
        for cycle in db.scalars(query)
        if cycle_season_year(cycle.season, cycle.planting_date) == where.season_year
    ]


def _season_expenses(where: SeasonFilter):
    """Expense rows of the farm and season; with a field, only that field's expenses."""
    query = select(Expense).where(
        Expense.farm_id == where.farm_id,
        Expense.season == where.season,
        Expense.season_year == where.season_year,
    )
    if where.field_id is not None:
        query = query.join(CropCycle, CropCycle.cycle_id == Expense.cycle_id).where(
            CropCycle.field_id == where.field_id
        )
    return query


def list_expenses(db: Session, user: User, where: SeasonFilter) -> list[ExpenseItem]:
    """Newest expense_date first, then the newest entry."""
    base = _season_expenses(where).subquery()
    rows = db.execute(
        select(
            base,
            ExpenseCategory.category_name,
            FarmField.field_name,
            User.first_name,
            User.last_name,
        )
        .join(ExpenseCategory, ExpenseCategory.category_id == base.c.category_id)
        .join(User, User.user_id == base.c.recorded_by)
        .outerjoin(CropCycle, CropCycle.cycle_id == base.c.cycle_id)
        .outerjoin(FarmField, FarmField.field_id == CropCycle.field_id)
        .order_by(base.c.expense_date.desc(), base.c.expense_id.desc())
    ).mappings()
    is_owner = where.role == FarmRole.OWNER
    return [
        ExpenseItem(
            expense_id=row["expense_id"],
            category_id=row["category_id"],
            category_name=row["category_name"],
            amount_php=row["amount_php"],
            expense_date=row["expense_date"],
            description=row["description"],
            quantity=row["quantity"],
            unit=row["unit"],
            cycle_id=row["cycle_id"],
            field_name=row["field_name"],
            season=row["season"],
            season_year=row["season_year"],
            recorded_by_name=f"{row['first_name']} {row['last_name']}",
            can_delete=is_owner or row["recorded_by"] == user.user_id,
        )
        for row in rows
    ]


def _created(expense: Expense) -> ExpenseCreated:
    return ExpenseCreated(
        expense_id=expense.expense_id, season=expense.season, season_year=expense.season_year
    )


def _saved_with_uuid(db: Session, user: User, farm_id: int, client_uuid: uuid.UUID):
    """The expense already saved under this client_uuid by the same caller on the same farm,
    or None when the uuid is new. 409 client_uuid_taken when someone else used it; the reply
    says nothing about that expense."""
    saved = db.scalar(select(Expense).where(Expense.client_uuid == client_uuid))
    if saved is None:
        return None
    if saved.farm_id != farm_id or saved.recorded_by != user.user_id:
        raise AppError(409, "client_uuid_taken")
    return saved


def create_expense(
    db: Session, user: User, farm_id: int, data: ExpenseCreate
) -> tuple[ExpenseCreated, bool]:
    """Save an expense and return it with True, or return the one already saved under the
    same client_uuid (an offline retry) with False.

    Errors: 403 not_farm_member; 409 client_uuid_taken; 422 expense_date_in_future,
    category_not_found, unit_required, quantity_required, cycle_not_in_farm,
    season_required, season_mismatch.
    """
    require_farm_member(db, user, farm_id)
    saved = _saved_with_uuid(db, user, farm_id, data.client_uuid)
    if saved is not None:
        return _created(saved), False

    if data.expense_date > philippine_today():
        raise AppError(422, "expense_date_in_future")
    if db.get(ExpenseCategory, data.category_id) is None:
        raise AppError(422, "category_not_found")
    if data.quantity is not None and data.unit is None:
        raise AppError(422, "unit_required")
    if data.unit is not None and data.quantity is None:
        raise AppError(422, "quantity_required")

    if data.cycle_id is not None:
        cycle = db.scalar(
            select(CropCycle)
            .join(FarmField, FarmField.field_id == CropCycle.field_id)
            .where(CropCycle.cycle_id == data.cycle_id, FarmField.farm_id == farm_id)
        )
        if cycle is None:
            raise AppError(422, "cycle_not_in_farm")
        season = cycle.season
        season_year = cycle_season_year(cycle.season, cycle.planting_date)
        sent_season_differs = data.season is not None and data.season != season
        sent_year_differs = data.season_year is not None and data.season_year != season_year
        if sent_season_differs or sent_year_differs:
            raise AppError(422, "season_mismatch")
    else:
        if data.season is None or data.season_year is None:
            raise AppError(422, "season_required")
        season, season_year = data.season, data.season_year

    expense = Expense(
        cycle_id=data.cycle_id,
        farm_id=farm_id,
        season=season,
        season_year=season_year,
        category_id=data.category_id,
        recorded_by=user.user_id,
        amount_php=data.amount_php,
        expense_date=data.expense_date,
        description=data.description,
        quantity=data.quantity,
        unit=data.unit,
        client_uuid=data.client_uuid,
        synced_at=datetime.now(UTC),
    )
    db.add(expense)
    try:
        db.commit()
    except IntegrityError as exc:
        # Two sends of the same entry at once: the other one was saved first.
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != _CLIENT_UUID_CONSTRAINT:
            raise
        saved = _saved_with_uuid(db, user, farm_id, data.client_uuid)
        return _created(saved), False
    return _created(expense), True


def delete_expense(db: Session, user: User, expense_id: int) -> None:
    """Remove an expense; allowed for the member who recorded it and for the farm owner.

    Errors: 404 expense_not_found (also when the caller is not a member of its farm);
    403 not_allowed.
    """
    expense = db.get(Expense, expense_id)
    role = farm_role_of(db, user, expense.farm_id) if expense is not None else None
    if role is None:
        raise AppError(404, "expense_not_found")
    if role != FarmRole.OWNER and expense.recorded_by != user.user_id:
        raise AppError(403, "not_allowed")
    db.delete(expense)
    db.commit()


def summary(db: Session, where: SeasonFilter) -> SeasonSummary:
    """Totals for the season. With a field, only that field's expenses and harvests count and
    whole-farm expenses are left out."""
    expenses = _season_expenses(where).subquery()
    by_category = dict(
        db.execute(
            select(expenses.c.category_id, func.sum(expenses.c.amount_php)).group_by(
                expenses.c.category_id
            )
        ).all()
    )
    whole_farm = Decimal(0)
    if where.field_id is None:
        whole_farm = db.scalar(
            select(func.coalesce(func.sum(expenses.c.amount_php), 0)).where(
                expenses.c.cycle_id.is_(None)
            )
        )
    cycle_ids = season_cycle_ids(db, where)
    gross = Decimal(0)
    if cycle_ids:
        gross = db.scalar(
            select(func.coalesce(func.sum(HarvestRecord.gross_income_php), 0)).where(
                HarvestRecord.cycle_id.in_(cycle_ids)
            )
        )
    categories = db.scalars(select(ExpenseCategory).order_by(ExpenseCategory.category_id))
    total = sum(by_category.values(), Decimal(0))
    return SeasonSummary(
        season=where.season,
        season_year=where.season_year,
        total_expenses_php=total,
        whole_farm_expenses_php=whole_farm,
        by_category=[
            CategoryAmount(
                category_name=c.category_name, amount_php=by_category.get(c.category_id, 0)
            )
            for c in categories
        ],
        gross_income_php=gross,
        net_profit_php=gross - total,
    )
