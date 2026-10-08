import asyncio
import hmac
import json
import logging
import secrets
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from .body_limit import BodyLimitMiddleware
from .config import get_settings
from .db import (
    Asset,
    Credential,
    Database,
    Job,
    LoginAttempt,
    Session,
    Step,
    User,
    WorkflowRecord,
    new_id,
    now,
)
from .media import asset_path, store_asset
from .model_catalog import CATALOG
from .schemas import (
    CloseReview,
    Graph,
    KeyInput,
    Login,
    Reconcile,
    SaveWorkflow,
    SubmitJob,
    UserCreate,
)
from .security import allowed_remote, cipher, digest, valid_asset_signature
from .validation import validate_execution
from .version import BUILD_REVISION, VERSION

log = logging.getLogger("genjutsu")
password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def create_app(settings=None, *, dispatch=True):
    settings = settings or get_settings()
    database = Database(settings)

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        with database.session.begin() as db:
            if not db.scalar(
                select(User).where(User.email == settings.admin_email.lower())
            ):
                db.add(
                    User(
                        email=settings.admin_email.lower(),
                        password_hash=password_hasher.hash(settings.admin_password),
                        admin=True,
                    )
                )
        task = None
        if dispatch and settings.temporal_enabled:
            from .temporal_client import dispatch_loop

            task = asyncio.create_task(dispatch_loop(app))
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        database.engine.dispose()

    app = FastAPI(
        title="Open Genjutsu",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        BodyLimitMiddleware, upload_limit=(settings.max_upload_mb + 1) * 1024 * 1024
    )
    app.state.settings = settings
    app.state.database = database
    app.state.temporal_ready = False

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Avoid reflecting passwords, API keys, or entire graph inputs in validation errors.
        return JSONResponse(
            {"detail": "요청 형식이 올바르지 않습니다."}, status_code=422
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        log.error(
            "request_failed path=%s type=%s", request.url.path, type(exc).__name__
        )
        return JSONResponse(
            {"detail": "서버 오류가 발생했습니다. 다시 시도하세요."}, status_code=500
        )

    @app.middleware("http")
    async def headers(request, call_next):
        length = request.headers.get("content-length")
        limit = (
            (settings.max_upload_mb + 1) * 1024 * 1024
            if request.url.path == "/api/assets"
            else 2 * 1024 * 1024
        )
        if length and (not length.isdigit() or int(length) > limit):
            return JSONResponse(
                {"detail": "요청 크기가 제한을 초과했습니다."}, status_code=413
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != settings.public_url.rstrip("/"):
                return JSONResponse(
                    {"detail": "허용되지 않은 요청 출처입니다."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def db_session():
        with database.session() as db:
            yield db

    def current_user(request: Request, db=Depends(db_session)):
        raw = request.cookies.get("genjutsu_session", "")
        s = db.get(Session, digest(raw)) if raw else None
        if not s or s.expires < now():
            raise HTTPException(401, "로그인이 필요합니다.")
        u = db.get(User, s.user_id)
        if not u or u.disabled:
            raise HTTPException(401, "로그인이 필요합니다.")
        if request.method not in {"GET", "HEAD"}:
            token = request.headers.get("x-csrf-token", "")
            if not token or not hmac.compare_digest(s.csrf_hash, digest(token)):
                raise HTTPException(403, "요청 인증이 만료됐습니다. 새로고침하세요.")
        return u

    def admin(user=Depends(current_user)):
        if not user.admin:
            raise HTTPException(403, "관리자 권한이 필요합니다.")
        return user

    def owned(db, cls, id, user):
        obj = db.get(cls, id)
        if not obj or obj.user_id != user.id:
            raise HTTPException(404, "항목을 찾을 수 없습니다.")
        return obj

    def workflow_response(w):
        return {
            "id": w.id,
            "title": w.title,
            "revision": w.revision,
            "graph": w.graph,
            "updated": w.updated.isoformat() + "Z",
        }

    def job_response(j, db):
        return {
            "id": j.id,
            "workflow_id": j.workflow_id,
            "title": j.graph["title"],
            "status": j.status,
            "cancel_requested": j.cancel_requested,
            "error": j.error,
            "created": j.created.isoformat() + "Z",
            "updated": j.updated.isoformat() + "Z",
            "review_note": j.review_note,
            "steps": [
                {
                    "node_id": s.node_id,
                    "status": s.status,
                    "output": s.output,
                    "error": s.error,
                    "provider_id": s.provider_id,
                    "provider": next(
                        (
                            n["data"]["provider"]
                            for n in j.graph["nodes"]
                            if n["id"] == s.node_id
                        ),
                        None,
                    ),
                }
                for s in db.scalars(select(Step).where(Step.job_id == j.id))
            ],
        }

    @app.get("/api/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/api/version")
    def version():
        return {"version": VERSION, "revision": BUILD_REVISION}

    @app.get("/api/models")
    def models(user=Depends(current_user)):
        return CATALOG

    @app.get("/api/readyz")
    def ready():
        with database.session() as db:
            db.execute(text("SELECT 1"))
        if settings.temporal_enabled and not app.state.temporal_ready:
            raise HTTPException(503, "작업 서비스 연결 대기 중")
        return {"status": "ready"}

    @app.post("/api/auth/login")
    def login(
        body: Login, request: Request, response: Response, db=Depends(db_session)
    ):
        bucket = digest(
            body.email.lower()
            + ":"
            + (request.client.host if request.client else "unknown")
        )
        a = db.scalar(
            select(LoginAttempt).where(LoginAttempt.key == bucket).with_for_update()
        )
        if not a:
            a = LoginAttempt(key=bucket, attempts=0, since=now())
            db.add(a)
        if a.since < now() - timedelta(minutes=15):
            a.attempts = 0
            a.since = now()
        if a.attempts >= 10:
            raise HTTPException(429, "로그인 시도가 많습니다. 15분 뒤 다시 시도하세요.")
        a.attempts += 1
        db.commit()
        u = db.scalar(select(User).where(User.email == body.email.lower()))
        try:
            valid = password_hasher.verify(
                u.password_hash if u else dummy_hash, body.password
            )
        except VerificationError:
            valid = False
        if not u or not valid or u.disabled:
            raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다.")
        raw = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        db.add(
            Session(
                token_hash=digest(raw),
                user_id=u.id,
                csrf_hash=digest(csrf),
                expires=now() + timedelta(hours=settings.session_hours),
            )
        )
        a.attempts = 0
        db.commit()
        for name, value, http_only in [
            ("genjutsu_session", raw, True),
            ("genjutsu_csrf", csrf, False),
        ]:
            response.set_cookie(
                name,
                value,
                httponly=http_only,
                secure=settings.secure_cookies,
                samesite="strict",
                max_age=settings.session_hours * 3600,
                path="/",
            )
        return {"id": u.id, "email": u.email, "admin": u.admin}

    @app.get("/api/auth/session")
    def session_info(request: Request, db=Depends(db_session)):
        raw = request.cookies.get("genjutsu_session", "")
        s = db.get(Session, digest(raw)) if raw else None
        u = db.get(User, s.user_id) if s and s.expires > now() else None
        return {
            "user": {"id": u.id, "email": u.email, "admin": u.admin}
            if u and not u.disabled
            else None
        }

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return {"id": user.id, "email": user.email, "admin": user.admin}

    @app.post("/api/auth/logout")
    def logout(
        request: Request,
        response: Response,
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        s = db.get(Session, digest(request.cookies["genjutsu_session"]))
        db.delete(s)
        db.commit()
        response.delete_cookie("genjutsu_session", path="/")
        response.delete_cookie("genjutsu_csrf", path="/")
        return {"ok": True}

    @app.post("/api/admin/users", status_code=201)
    def create_user(body: UserCreate, user=Depends(admin), db=Depends(db_session)):
        if "@" not in body.email:
            raise HTTPException(422, "올바른 이메일을 입력하세요.")
        u = User(
            email=body.email.lower(), password_hash=password_hasher.hash(body.password)
        )
        db.add(u)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "이미 존재하는 사용자입니다.")
        return {"id": u.id, "email": u.email}

    @app.get("/api/credentials")
    def credentials(user=Depends(current_user), db=Depends(db_session)):
        return {
            "providers": list(
                set(
                    db.scalars(
                        select(Credential.provider).where(Credential.user_id == user.id)
                    )
                )
            )
        }

    @app.put("/api/credentials/{provider}")
    def save_key(
        provider: str,
        body: KeyInput,
        user=Depends(current_user),
        db=Depends(db_session),
    ):
        if provider not in {"openrouter", "fal", "replicate", "custom", "gpu"}:
            raise HTTPException(422, "지원하지 않는 공급자입니다.")
        endpoint = body.endpoint.rstrip("/") if provider in {"custom", "gpu"} else ""
        if provider in {"custom", "gpu"}:
            try:
                allowed_remote(endpoint, settings, custom=True)
            except ValueError:
                raise HTTPException(422, "운영자가 허용한 API 주소에 키를 연결하세요.")
        # Serialize mutations with submission so credentials/quota cannot race.
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        if db.scalar(
            select(Job.id).where(
                Job.user_id == user.id,
                Job.status.in_(["QUEUED", "RUNNING", "NEEDS_REVIEW"]),
            )
        ):
            raise HTTPException(409, "진행 중인 작업이 끝난 뒤 키를 변경하세요.")
        key = db.scalar(
            select(Credential).where(
                Credential.user_id == user.id,
                Credential.provider == provider,
                Credential.endpoint == endpoint,
            )
        )
        if not key:
            key = Credential(user_id=user.id, provider=provider, endpoint=endpoint)
            db.add(key)
        key.encrypted_key = (
            cipher(settings.secret_key).encrypt(body.key.encode()).decode()
        )
        db.commit()
        return {"ok": True}

    @app.delete("/api/credentials/{provider}")
    def delete_key(provider: str, user=Depends(current_user), db=Depends(db_session)):
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        if db.scalar(
            select(Job.id).where(
                Job.user_id == user.id,
                Job.status.in_(["QUEUED", "RUNNING", "NEEDS_REVIEW"]),
            )
        ):
            raise HTTPException(409, "진행 중인 작업이 끝난 뒤 키를 삭제하세요.")
        keys = list(
            db.scalars(
                select(Credential).where(
                    Credential.user_id == user.id, Credential.provider == provider
                )
            )
        )
        for key in keys:
            db.delete(key)
        db.commit()
        return {"ok": True}

    @app.get("/api/workflows")
    def list_workflows(user=Depends(current_user), db=Depends(db_session)):
        return [
            workflow_response(w)
            for w in db.scalars(
                select(WorkflowRecord)
                .where(WorkflowRecord.user_id == user.id)
                .order_by(WorkflowRecord.updated.desc())
                .limit(100)
            )
        ]

    @app.post("/api/workflows", status_code=201)
    def create_workflow(
        body: SaveWorkflow, user=Depends(current_user), db=Depends(db_session)
    ):
        if (
            db.scalar(
                select(func.count())
                .select_from(WorkflowRecord)
                .where(WorkflowRecord.user_id == user.id)
            )
            >= 100
        ):
            raise HTTPException(409, "워크플로는 최대 100개입니다.")
        w = WorkflowRecord(
            user_id=user.id,
            title=body.graph.title,
            graph=body.graph.model_dump(exclude_none=True),
        )
        db.add(w)
        db.commit()
        return workflow_response(w)

    @app.put("/api/workflows/{id}")
    def save_workflow(
        id: str, body: SaveWorkflow, user=Depends(current_user), db=Depends(db_session)
    ):
        w = db.scalar(
            select(WorkflowRecord)
            .where(WorkflowRecord.id == id, WorkflowRecord.user_id == user.id)
            .with_for_update()
        )
        if not w:
            raise HTTPException(404, "워크플로를 찾을 수 없습니다.")
        if w.revision != body.revision:
            raise HTTPException(
                409, "다른 창에서 수정됐습니다. 서버 버전을 다시 불러오세요."
            )
        w.graph = body.graph.model_dump(exclude_none=True)
        w.title = body.graph.title
        w.revision += 1
        w.updated = now()
        db.commit()
        return workflow_response(w)

    @app.post("/api/assets", status_code=201)
    async def upload(
        file: UploadFile, user=Depends(current_user), db=Depends(db_session)
    ):
        limit = settings.max_upload_mb * 1024 * 1024
        size = 0
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "upload"
            with path.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, "업로드 크기를 초과했습니다.")
                    out.write(chunk)
            try:
                a = await asyncio.to_thread(
                    store_asset, settings, user.id, file.filename or "media", path
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc))
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        used = db.scalar(
            select(func.coalesce(func.sum(Asset.size), 0)).where(
                Asset.user_id == user.id
            )
        )
        if used + a.size > settings.user_storage_mb * 1024 * 1024:
            asset_path(settings, a.id).unlink(missing_ok=True)
            raise HTTPException(409, "미디어 저장 한도를 초과했습니다.")
        db.add(a)
        try:
            db.commit()
        except Exception:
            asset_path(settings, a.id).unlink(missing_ok=True)
            raise
        return {
            "id": a.id,
            "filename": a.filename,
            "mime": a.mime,
            "size": a.size,
            "metadata": a.metadata_json,
        }

    @app.get("/api/assets/{id}/content")
    def media_content(
        id: str,
        request: Request,
        expires: int = 0,
        token: str = "",
        download: bool = False,
        db=Depends(db_session),
    ):
        a = db.get(Asset, id)
        if not a:
            raise HTTPException(404, "미디어를 찾을 수 없습니다.")
        if not valid_asset_signature(settings.secret_key, id, expires, token):
            user = current_user(request, db)
            if a.user_id != user.id:
                raise HTTPException(404, "미디어를 찾을 수 없습니다.")
        if not asset_path(settings, id).is_file():
            raise HTTPException(404, "미디어 파일을 찾을 수 없습니다.")
        return FileResponse(
            asset_path(settings, id),
            media_type=a.mime,
            filename=a.filename if download else None,
        )

    @app.get("/api/assets")
    def list_assets(user=Depends(current_user), db=Depends(db_session)):
        return [
            {"id": a.id, "filename": a.filename, "mime": a.mime, "size": a.size}
            for a in db.scalars(
                select(Asset)
                .where(Asset.user_id == user.id)
                .order_by(Asset.created.desc())
                .limit(500)
            )
        ]

    @app.delete("/api/assets/{id}")
    def delete_asset(id: str, user=Depends(current_user), db=Depends(db_session)):
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        a = owned(db, Asset, id, user)
        graphs = [
            w.graph
            for w in db.scalars(
                select(WorkflowRecord).where(WorkflowRecord.user_id == user.id)
            )
        ] + [j.graph for j in db.scalars(select(Job).where(Job.user_id == user.id))]
        if any(n["data"].get("assetId") == id for g in graphs for n in g["nodes"]):
            raise HTTPException(
                409, "프로젝트 또는 작업 기록에서 사용 중인 미디어입니다."
            )
        steps = db.scalars(select(Step).join(Job).where(Job.user_id == user.id))
        if any((step.output or {}).get("asset_id") == id for step in steps):
            raise HTTPException(409, "작업 기록에서 사용 중인 결과입니다.")
        db.delete(a)
        db.commit()
        asset_path(settings, id).unlink(missing_ok=True)
        return {"ok": True}

    @app.delete("/api/workflows/{id}")
    def delete_workflow(id: str, user=Depends(current_user), db=Depends(db_session)):
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        w = owned(db, WorkflowRecord, id, user)
        if db.scalar(select(Job.id).where(Job.workflow_id == id)):
            raise HTTPException(
                409, "작업 내역에서 이 프로젝트의 기록을 먼저 삭제하세요."
            )
        db.delete(w)
        db.commit()
        return {"ok": True}

    @app.delete("/api/jobs/{id}")
    def delete_job(id: str, user=Depends(current_user), db=Depends(db_session)):
        j = owned(db, Job, id, user)
        if j.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            raise HTTPException(
                409, "진행 중이거나 확인 대기 중인 작업은 삭제할 수 없습니다."
            )
        db.execute(delete(Step).where(Step.job_id == id))
        db.delete(j)
        db.commit()
        return {"ok": True}

    @app.post("/api/workflows/{id}/validate")
    def preflight(id: str, user=Depends(current_user), db=Depends(db_session)):
        w = owned(db, WorkflowRecord, id, user)
        return validate_execution(Graph.model_validate(w.graph), db, user.id, settings)

    @app.post("/api/workflows/{id}/jobs", status_code=202)
    def submit(
        id: str, body: SubmitJob, user=Depends(current_user), db=Depends(db_session)
    ):
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        w = owned(db, WorkflowRecord, id, user)
        existing = db.scalar(
            select(Job).where(
                Job.user_id == user.id, Job.request_key == body.request_key
            )
        )
        fingerprint = digest(
            json.dumps({"id": id, "revision": body.revision}, sort_keys=True)
        )
        if existing:
            if existing.request_hash != fingerprint:
                raise HTTPException(409, "요청 키가 다른 실행에 이미 사용됐습니다.")
            return job_response(existing, db)
        if w.revision != body.revision:
            raise HTTPException(409, "실행할 워크플로 버전이 변경됐습니다.")
        graph = Graph.model_validate(w.graph)
        check = validate_execution(graph, db, user.id, settings)
        if check["errors"]:
            raise HTTPException(
                422, {"errors": check["errors"], "warnings": check["warnings"]}
            )
        if check["paid_steps"] and not body.confirm_paid:
            raise HTTPException(422, "API 요금 발생 확인이 필요합니다.")
        active = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.user_id == user.id,
                Job.status.in_(["QUEUED", "RUNNING", "NEEDS_REVIEW"]),
            )
        )
        if active >= settings.max_active_jobs:
            raise HTTPException(409, "동시에 실행할 수 있는 작업 한도를 초과했습니다.")
        j = Job(
            id=new_id(),
            user_id=user.id,
            workflow_id=w.id,
            request_key=body.request_key,
            request_hash=fingerprint,
            graph=w.graph,
        )
        db.add(j)
        db.flush()
        for n in graph.nodes:
            db.add(Step(job_id=j.id, node_id=n.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            j = db.scalar(
                select(Job).where(
                    Job.user_id == user.id, Job.request_key == body.request_key
                )
            )
            if not j:
                raise
        return job_response(j, db)

    @app.get("/api/jobs")
    def jobs(user=Depends(current_user), db=Depends(db_session)):
        return [
            job_response(j, db)
            for j in db.scalars(
                select(Job)
                .where(Job.user_id == user.id)
                .order_by(Job.created.desc())
                .limit(50)
            )
        ]

    @app.get("/api/admin/jobs/review")
    def review_jobs(user=Depends(admin), db=Depends(db_session)):
        return [
            job_response(j, db)
            for j in db.scalars(
                select(Job)
                .where(Job.status == "NEEDS_REVIEW")
                .order_by(Job.updated)
                .limit(50)
            )
        ]

    @app.get("/api/admin/operations")
    def operations(user=Depends(admin), db=Depends(db_session)):
        counts = dict(
            db.execute(
                select(Job.status, func.count(Job.id)).group_by(Job.status)
            ).all()
        )
        oldest_queued = db.scalar(
            select(func.min(Job.created)).where(Job.status == "QUEUED")
        )
        oldest_review = db.scalar(
            select(func.min(Job.updated)).where(Job.status == "NEEDS_REVIEW")
        )
        completed = db.execute(
            select(Job.created, Job.updated)
            .where(Job.status == "SUCCEEDED")
            .order_by(Job.updated.desc())
            .limit(100)
        ).all()
        durations = sorted(
            max(0, (end - start).total_seconds()) for start, end in completed
        )
        disk = shutil.disk_usage(settings.data_dir)
        return {
            "jobs": counts,
            "oldest_queued_seconds": max(0, (now() - oldest_queued).total_seconds())
            if oldest_queued
            else 0,
            "oldest_review_seconds": max(0, (now() - oldest_review).total_seconds())
            if oldest_review
            else 0,
            "recent_completed_samples": len(durations),
            "recent_p95_seconds": durations[(len(durations) * 95 + 99) // 100 - 1]
            if durations
            else None,
            "steps": dict(
                db.execute(
                    select(Step.status, func.count(Step.id)).group_by(Step.status)
                ).all()
            ),
            "media_bytes": db.scalar(select(func.sum(Asset.size))) or 0,
            "media_count": db.scalar(select(func.count(Asset.id))) or 0,
            "disk_free_bytes": disk.free,
            "disk_total_bytes": disk.total,
            "temporal_connected": app.state.temporal_ready,
        }

    @app.get("/api/jobs/{id}")
    def job(id: str, user=Depends(current_user), db=Depends(db_session)):
        return job_response(owned(db, Job, id, user), db)

    @app.post("/api/jobs/{id}/cancel")
    def cancel(id: str, user=Depends(current_user), db=Depends(db_session)):
        j = owned(db, Job, id, user)
        if j.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return job_response(j, db)
        j.cancel_requested = True
        if j.status == "QUEUED" and not j.dispatched:
            j.status = "CANCELLED"
            j.dispatched = True
        j.updated = now()
        db.commit()
        return job_response(j, db)

    @app.post("/api/admin/jobs/{id}/reconcile")
    def reconcile(
        id: str, body: Reconcile, user=Depends(admin), db=Depends(db_session)
    ):
        j = db.scalar(select(Job).where(Job.id == id).with_for_update())
        if not j or j.status != "NEEDS_REVIEW" or j.cancel_requested:
            raise HTTPException(409, "확인 대기 중인 작업만 복구할 수 있습니다.")
        s = db.scalar(
            select(Step).where(Step.job_id == id, Step.node_id == body.node_id)
        )
        node = next((n for n in j.graph["nodes"] if n["id"] == body.node_id), None)
        if (
            not s
            or s.status != "UNKNOWN"
            or not node
            or node["data"]["provider"] not in {"fal", "replicate"}
        ):
            raise HTTPException(
                422, "fal 또는 Replicate의 접수 ID를 확인해 입력하세요."
            )
        if j.updated > now() - timedelta(minutes=5):
            raise HTTPException(409, "기존 실행 종료를 확인한 뒤 5분 이상 대기하세요.")
        from .providers import recovered_ticket

        s.provider_id = body.provider_id
        s.ticket = recovered_ticket(node["data"], body.provider_id, settings)
        s.status = "SUBMITTED"
        s.error = None
        j.status = "QUEUED"
        j.error = None
        j.dispatched = False
        j.run_revision += 1
        j.updated = now()
        db.commit()
        return job_response(j, db)

    @app.post("/api/admin/jobs/{id}/close-review")
    def close_review(
        id: str, body: CloseReview, user=Depends(admin), db=Depends(db_session)
    ):
        j = db.scalar(select(Job).where(Job.id == id).with_for_update())
        if not j or j.status != "NEEDS_REVIEW":
            raise HTTPException(409, "확인 대기 중인 작업만 종료할 수 있습니다.")
        if j.updated > now() - timedelta(minutes=5):
            raise HTTPException(409, "기존 실행 종료를 확인한 뒤 5분 이상 대기하세요.")
        j.review_note = (
            f"admin={user.id};closed={now().isoformat()};reason={body.reason}"
        )
        j.status = "CANCELLED" if j.cancel_requested else "FAILED"
        j.error = "운영자가 공급자 실행을 확인하고 작업을 종료했습니다."
        j.updated = now()
        db.commit()
        return job_response(j, db)

    if settings.static_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=settings.static_dir / "assets"),
            name="static-assets",
        )

        @app.get("/{path:path}")
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            if path == "favicon.svg":
                return FileResponse(settings.static_dir / "favicon.svg")
            return FileResponse(settings.static_dir / "index.html")

    return app
