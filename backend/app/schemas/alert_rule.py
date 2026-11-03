from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.models.enums import AlertAggregation, AlertOperator, AlertParameter, AlertSeverity

Template = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AlertRuleItem(BaseModel):
    """One ALERT_RULE row as GET /admin/alert-rules returns it."""

    model_config = ConfigDict(from_attributes=True)

    rule_id: int
    rule_name: str
    parameter: AlertParameter
    aggregation: AlertAggregation
    operator: AlertOperator
    threshold: float
    lookahead_hours: int
    severity: AlertSeverity
    message_template: str
    source_reference: str
    is_active: bool


class AlertRuleUpdate(BaseModel):
    """PATCH /admin/alert-rules/{rule_id} body: any of these, never null. Rules can't be
    added or deleted here. The template's placeholders are checked by the service
    (422 invalid_template)."""

    model_config = ConfigDict(extra="forbid")

    is_active: StrictBool | None = None
    # ALERT_RULE.threshold NUMERIC(6,2), greater than 0.
    threshold: Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)] | None = None
    message_template: Template | None = None

    @model_validator(mode="after")
    def _no_nulls(self) -> "AlertRuleUpdate":
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} may not be null")
        return self
