"""特殊排程要求(交互设计 §4④)。仅管理员。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ..deps import DB, AdminUser
from ..models import Rule
from ..rules import rule_types, serialize_rule, validate_params
from ..schemas import RuleIn, RuleOut, RulePatch, RuleTypeOut
from .events import load_event

router = APIRouter(tags=["rules"])


@router.get("/rule-types", response_model=list[RuleTypeOut])
def list_rule_types(_admin: AdminUser) -> list[RuleTypeOut]:
    return rule_types()


@router.get("/events/{event_id}/rules", response_model=list[RuleOut])
def list_rules(event_id: int, db: DB, admin: AdminUser) -> list[RuleOut]:
    event = load_event(db, event_id, admin)
    return [serialize_rule(event, r) for r in event.rules]


@router.post("/events/{event_id}/rules", response_model=RuleOut, status_code=201)
def create_rule(event_id: int, body: RuleIn, db: DB, admin: AdminUser) -> RuleOut:
    event = load_event(db, event_id, admin)
    params = validate_params(event, body.type, body.params)
    max_order = db.scalar(select(func.max(Rule.sort_order)).where(Rule.event_id == event.id)) or 0
    rule = Rule(event_id=event.id, type=body.type, params=params, enabled=body.enabled, sort_order=max_order + 1)
    db.add(rule)
    db.commit()
    db.refresh(event)
    return serialize_rule(event, rule)


def _get_rule(db, rule_id: int) -> Rule:  # noqa: ANN001
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="要求不存在")
    return rule


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RulePatch, db: DB, admin: AdminUser) -> RuleOut:
    rule = _get_rule(db, rule_id)
    event = load_event(db, rule.event_id, admin)
    if body.params is not None:
        rule.params = validate_params(event, rule.type, body.params)
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.sort_order is not None:
        rule.sort_order = body.sort_order
    db.commit()
    db.refresh(event)
    return serialize_rule(event, rule)


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: DB, admin: AdminUser) -> None:
    rule = _get_rule(db, rule_id)
    load_event(db, rule.event_id, admin)
    db.delete(rule)
    db.commit()
