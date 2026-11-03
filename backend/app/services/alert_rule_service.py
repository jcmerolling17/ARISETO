"""Alert rules for cooperative administrators (DFD 5.5, until an admin screen exists):
list them and change is_active, threshold or message_template. Rules can't be added or
deleted. A change applies from the next evaluation; alerts already issued stay as they are."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import AlertRule
from app.schemas.alert_rule import AlertRuleItem, AlertRuleUpdate

PLACEHOLDERS = re.compile(r"\{(?:value|hours)\}")


def is_valid_template(template: str) -> bool:
    """Only {value} and {hours} may appear in braces; any other brace is refused."""
    rest = PLACEHOLDERS.sub("", template)
    return "{" not in rest and "}" not in rest


def list_rules(db: Session) -> list[AlertRuleItem]:
    return [
        AlertRuleItem.model_validate(rule)
        for rule in db.scalars(select(AlertRule).order_by(AlertRule.rule_id))
    ]


def update_rule(db: Session, rule_id: int, data: AlertRuleUpdate) -> AlertRuleItem:
    """Errors in order: 404 rule_not_found, then 422 invalid_template."""
    rule = db.get(AlertRule, rule_id, with_for_update=True)
    if rule is None:
        raise AppError(404, "rule_not_found")
    changes = data.model_dump(exclude_unset=True)
    if "message_template" in changes and not is_valid_template(changes["message_template"]):
        raise AppError(422, "invalid_template")
    for name, value in changes.items():
        setattr(rule, name, value)
    db.commit()
    return AlertRuleItem.model_validate(rule)
