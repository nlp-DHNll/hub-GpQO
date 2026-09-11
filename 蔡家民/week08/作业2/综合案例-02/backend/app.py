# -*- coding: utf-8 -*-
"""深度研究助手 FastAPI：认证、任务、SSE、版本、导出与管理接口。"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

from . import config, storage
from .auth import COOKIE_NAME, create_session, require_auth, verify_password
from .exporters import to_html, to_markdown, to_pdf
from .models import AdminStats, LoginRequest, ResearchRecord, ResearchRequest, Status
from .queueing import enqueue
from .rate_limit import enforce

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s | %(message)s")
    storage.recover_interrupted()
    yield


app = FastAPI(title="深度研究助手 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([config.FRONTEND_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"])),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "database": "ok", "model_configured": bool(config.OPENAI_API_KEY),
            "search_configured": bool(config.BOCHA_API_KEY), "auth_configured": bool(config.SHARED_PASSWORD_HASH)}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    enforce(request, "login", 8, 60)
    if not verify_password(payload.password):
        raise HTTPException(status_code=401, detail="密码错误或服务尚未配置共享密码")
    response.set_cookie(COOKIE_NAME, create_session(), max_age=config.SESSION_TTL_SECONDS,
                        httponly=True, secure=config.COOKIE_SECURE, samesite="lax", path="/")
    return {"authenticated": True}


@app.post("/api/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"authenticated": False}


@app.get("/api/auth/me")
async def me(_: None = Depends(require_auth)) -> dict:
    return {"authenticated": True}


@app.post("/api/research", status_code=202)
async def start_research(payload: ResearchRequest, request: Request, _: None = Depends(require_auth)) -> dict:
    enforce(request, "create", 10, 60)
    research_id = uuid.uuid4().hex
    try:
        rec = storage.create(research_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    enqueue(research_id)
    return {"research_id": research_id, "status": rec.status, "version": rec.version}


@app.get("/api/research", response_model=list[ResearchRecord])
async def list_research(_: None = Depends(require_auth)) -> list[ResearchRecord]:
    return [_public_record(rec) for rec in storage.list_all()]


@app.get("/api/research/{rid}", response_model=ResearchRecord)
async def get_research(rid: str, _: None = Depends(require_auth)) -> ResearchRecord:
    return _public_record(_must_get(rid))


@app.get("/api/research/{rid}/versions", response_model=list[ResearchRecord])
async def get_versions(rid: str, _: None = Depends(require_auth)) -> list[ResearchRecord]:
    rec = _must_get(rid)
    return [_public_record(item) for item in storage.versions_for(rec.root_id or rec.research_id)]


@app.get("/api/research/{rid}/events")
async def research_events(rid: str, request: Request, _: None = Depends(require_auth)) -> StreamingResponse:
    _must_get(rid)

    async def stream():
        previous = ""
        while not await request.is_disconnected():
            rec = storage.get(rid)
            if rec is None:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                break
            public = _public_record(rec)
            payload = public.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            if rec.status in {Status.completed, Status.failed, Status.cancelled}:
                yield f"event: done\ndata: {json.dumps({'status': rec.status.value})}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/research/{rid}/cancel", status_code=202)
async def cancel_research(rid: str, _: None = Depends(require_auth)) -> dict:
    rec = _must_get(rid)
    if rec.status not in {Status.queued, Status.pending, Status.running}:
        raise HTTPException(status_code=409, detail="当前状态不可取消")
    rec.status = Status.cancelled if rec.status in {Status.queued, Status.pending} else Status.cancelling
    rec.current_step = "正在安全取消"
    storage.save(rec)
    return {"status": rec.status}


@app.post("/api/research/{rid}/retry", status_code=202)
async def retry_research(rid: str, request: Request, _: None = Depends(require_auth)) -> dict:
    enforce(request, "create", 10, 60)
    old = _must_get(rid)
    if old.status not in {Status.failed, Status.cancelled}:
        raise HTTPException(status_code=409, detail="仅失败或已取消任务可重试")
    payload = ResearchRequest(topic=old.topic, goal=old.goal, date_range=old.date_range,
                              region=old.region, audience=old.audience, depth=old.depth)
    new_id = uuid.uuid4().hex
    storage.create(new_id, payload)
    enqueue(new_id)
    return {"research_id": new_id, "status": "queued"}


@app.delete("/api/research/{rid}")
async def delete_research(rid: str, _: None = Depends(require_auth)) -> dict:
    rec = _must_get(rid)
    if rec.status in {Status.running, Status.cancelling}:
        raise HTTPException(status_code=409, detail="请先取消运行中的任务")
    storage.delete_one(rid)
    return {"deleted": True}


@app.get("/api/research/{rid}/export/{kind}")
async def export_report(rid: str, kind: str, _: None = Depends(require_auth)) -> Response:
    rec = _must_get(rid)
    if rec.status != Status.completed or not rec.report:
        raise HTTPException(status_code=409, detail="报告尚未完成")
    filename = f"research-{rid[:8]}"
    if kind == "markdown":
        return Response(to_markdown(rec), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'})
    if kind == "html":
        return HTMLResponse(to_html(rec), headers={"Content-Disposition": f'attachment; filename="{filename}.html"'})
    if kind == "pdf":
        try:
            body = to_pdf(rec)
        except Exception as exc:  # noqa: BLE001
            logger.exception("PDF 导出失败")
            raise HTTPException(status_code=503, detail="PDF 渲染服务暂不可用") from exc
        return Response(body, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})
    raise HTTPException(status_code=404, detail="不支持的导出格式")


@app.get("/api/admin/stats", response_model=AdminStats)
async def admin_stats(_: None = Depends(require_auth)) -> AdminStats:
    records = storage.list_all()
    counts = {status.value: sum(rec.status == status for rec in records) for status in Status}
    return AdminStats(total=len(records), queued=counts["queued"] + counts["pending"], running=counts["running"] + counts["cancelling"],
                      completed=counts["completed"], failed=counts["failed"], cancelled=counts["cancelled"],
                      searches=sum(rec.usage.searches for rec in records), model_calls=sum(rec.usage.model_calls for rec in records))


@app.get("/api/admin/failures")
async def admin_failures(_: None = Depends(require_auth)) -> list[dict]:
    return [{"research_id": rec.research_id, "topic": rec.topic, "updated_at": rec.updated_at,
             "error": rec.error or rec.friendly_error} for rec in storage.list_all() if rec.status == Status.failed]


@app.delete("/api/admin/terminal")
async def clear_terminal(_: None = Depends(require_auth)) -> dict:
    return {"deleted": storage.delete_terminal()}


def _must_get(rid: str) -> ResearchRecord:
    rec = storage.get(rid)
    if rec is None:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return rec


def _public_record(rec: ResearchRecord) -> ResearchRecord:
    return rec.model_copy(update={"error": None})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)
