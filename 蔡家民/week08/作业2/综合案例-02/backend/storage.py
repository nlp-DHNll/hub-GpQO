# -*- coding: utf-8 -*-
"""研究记录存储：完整 JSON 文档 + 可查询的关系字段。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select

from . import config
from .db import ResearchRow, SessionLocal, init_db
from .models import ResearchLimits, ResearchRecord, ResearchRequest, Status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(rid: str, request: ResearchRequest) -> ResearchRecord:
    init_db()
    now = _now()
    limits = ResearchLimits(**config.DEPTH_LIMITS[request.depth.value])
    root_id = rid
    version = 1
    if request.parent_id:
        parent = get(request.parent_id)
        if parent is None or parent.status != Status.completed:
            raise ValueError("仅可对已完成报告发起补充研究")
        root_id = parent.root_id or parent.research_id
        version = max((r.version for r in versions_for(root_id)), default=0) + 1
    rec = ResearchRecord(
        research_id=rid, topic=request.topic, goal=request.goal,
        date_range=request.date_range, region=request.region, audience=request.audience,
        depth=request.depth, status=Status.queued, created_at=now, updated_at=now,
        limits=limits, parent_id=request.parent_id, root_id=root_id, version=version,
        follow_up=request.follow_up,
    )
    save(rec)
    return rec


def save(rec: ResearchRecord, error_detail: str | None = None) -> None:
    init_db()
    rec.updated_at = _now()
    payload = rec.model_dump(mode="json")
    with SessionLocal.begin() as session:
        row = session.get(ResearchRow, rec.research_id)
        if row is None:
            row = ResearchRow(
                research_id=rec.research_id, root_id=rec.root_id or rec.research_id,
                parent_id=rec.parent_id, version=rec.version, topic=rec.topic,
                status=rec.status.value, document=payload, error_detail=error_detail,
            )
            session.add(row)
        else:
            row.root_id = rec.root_id or rec.research_id
            row.parent_id = rec.parent_id
            row.version = rec.version
            row.topic = rec.topic
            row.status = rec.status.value
            row.document = payload
            if error_detail is not None:
                row.error_detail = error_detail


def get(rid: str) -> ResearchRecord | None:
    init_db()
    with SessionLocal() as session:
        row = session.get(ResearchRow, rid)
        return ResearchRecord.model_validate(row.document) if row else None


def list_all() -> list[ResearchRecord]:
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(select(ResearchRow).order_by(ResearchRow.created_at.desc())).all()
        return [ResearchRecord.model_validate(row.document) for row in rows]


def versions_for(root_id: str) -> list[ResearchRecord]:
    init_db()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ResearchRow).where(ResearchRow.root_id == root_id).order_by(ResearchRow.version)
        ).all()
        return [ResearchRecord.model_validate(row.document) for row in rows]


def update_status(rid: str, status: str, error: str | None = None, friendly_error: str | None = None) -> None:
    rec = get(rid)
    if rec is None:
        return
    rec.status = Status(status)
    if error is not None:
        rec.error = error
    if friendly_error is not None:
        rec.friendly_error = friendly_error
    save(rec, error_detail=error)


def delete_one(rid: str) -> bool:
    init_db()
    with SessionLocal.begin() as session:
        result = session.execute(delete(ResearchRow).where(ResearchRow.research_id == rid))
        return bool(result.rowcount)


def delete_terminal() -> int:
    init_db()
    terminal = [Status.completed.value, Status.failed.value, Status.cancelled.value]
    with SessionLocal.begin() as session:
        result = session.execute(delete(ResearchRow).where(ResearchRow.status.in_(terminal)))
        return int(result.rowcount or 0)


def recover_interrupted() -> int:
    """服务重启时把未完成任务安全标为失败，允许用户点击重试。"""
    count = 0
    for rec in list_all():
        if rec.status in {Status.pending, Status.queued, Status.running, Status.cancelling}:
            rec.status = Status.failed
            rec.friendly_error = "服务曾重启，此任务已安全停止，请点击重试。"
            rec.error = "interrupted by service restart"
            save(rec, error_detail=rec.error)
            count += 1
    return count


if __name__ == "__main__":
    init_db()
    print("storage 自检 OK")
