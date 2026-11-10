from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_active_user
from app.db.session import get_db
from app.models import User
from app.models.enums import ActivityStatus
from app.schemas.activity import (
    ActivityCreate,
    ActivityItem,
    ActivityUpdate,
    CycleActivities,
    FarmActivities,
)
from app.services import calendar_service

router = APIRouter(tags=["calendar"])


@router.get("/cycles/{cycle_id}/activities", response_model=CycleActivities)
def list_cycle_activities(
    cycle_id: int,
    status: ActivityStatus | None = None,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> CycleActivities:
    """A crop cycle and its tasks by date, then time (tasks without a time last). from and
    to keep the tasks with any day of their range between them. Members of the farm only.

    Errors: 404 cycle_not_found, also when the caller is not a member of the cycle's farm.
    """
    return calendar_service.list_cycle_activities(db, user, cycle_id, status, from_, to)


@router.get("/farms/{farm_id}/activities", response_model=FarmActivities)
def list_farm_activities(
    farm_id: int,
    field_id: int | None = None,
    status: ActivityStatus | None = None,
    q: str | None = Query(None, max_length=100),
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> FarmActivities:
    """Tasks of each field's current cycle; q searches titles, ignoring case.

    Errors: 403 not_farm_member, also for a farm that does not exist; 422 field_not_in_farm.
    """
    return calendar_service.list_farm_activities(
        db,
        user,
        farm_id,
        field_id=field_id,
        status=status,
        q=q,
        from_=from_,
        to=to,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/cycles/{cycle_id}/activities",
    status_code=status.HTTP_201_CREATED,
    response_model=ActivityItem,
)
def create_activity(
    cycle_id: int,
    data: ActivityCreate,
    response: Response,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> ActivityItem:
    """Add a custom task (task_type 'other'). A client_uuid already saved on this cycle
    returns that task with 200 instead of a duplicate.

    Errors: 404 cycle_not_found, also for non-members; 409 client_uuid_taken, cycle_closed;
    422 date_out_of_range.
    """
    item, is_new = calendar_service.create_activity(db, user, cycle_id, data)
    if not is_new:
        response.status_code = status.HTTP_200_OK
    return item


@router.patch("/activities/{activity_id}", response_model=ActivityItem)
def update_activity(
    activity_id: int,
    data: ActivityUpdate,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> ActivityItem:
    """Mark a task done, skipped or pending, reschedule it, or change its reminder or notes;
    title and growth_stage only on custom tasks.

    Errors: 404 activity_not_found, also for non-members; 409 cycle_closed; 422
    not_editable, date_out_of_range.
    """
    return calendar_service.update_activity(db, user, activity_id, data)


@router.delete("/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    activity_id: int,
    user: User = Depends(require_active_user),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a custom task; a generated one can only be skipped.

    Errors: 404 activity_not_found, also for non-members; 409 cycle_closed, generated_task.
    """
    calendar_service.delete_activity(db, user, activity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
