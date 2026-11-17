"""Run with: python -m processor (local-only by default)."""
import asyncio
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm
from .engine import Engine
from .folders import create_folder, list_folders
from .store import Store, uid

ROOT = Path(__file__).resolve().parent.parent


class ConnectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str
    model: str = Field(min_length=1, max_length=150, pattern=r"^[a-zA-Z0-9_.:/-]+$")
    base_url: str = ""
    api_key: str = ""
    input_rate: Optional[float] = Field(default=None, ge=0, le=100000)
    output_rate: Optional[float] = Field(default=None, ge=0, le=100000)


class ConditionInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    conditions: list[str] = Field(min_length=1, max_length=100)


class ProfileInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    input_folder: str = Field(min_length=1)
    output_folder: str = Field(min_length=1)
    connection_id: str
    condition_ids: list[str] = Field(min_length=1)
    threshold: float = Field(default=70, ge=0, lt=100)


class LoginInput(BaseModel):
    username: str
    password: str


class FolderInput(BaseModel):
    parent: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=255)


def create_app(data_dir=None):
    store = Store(data_dir or os.environ.get("GOLDEN_DATA_DIR", ROOT / "data"))
    engine = Engine(store)
    sessions, failures = {}, {}

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.close()

    app = FastAPI(title="Golden", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.engine = store, engine

    @app.middleware("http")
    async def auth(request, call_next):
        path = request.url.path
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        if path.startswith("/api/") and path != "/api/login":
            token = request.cookies.get("golden_session", "")
            if sessions.get(token, 0) < time.time():
                sessions.pop(token, None)
                return JSONResponse({"detail": "Please sign in to continue."}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_input(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": str(error).strip("'")}, status_code=404)

    @app.exception_handler(OSError)
    async def filesystem_error(request, error):
        return JSONResponse({"detail": "Cannot access this folder or file. Check its path and permissions."}, status_code=400)

    @app.post("/api/login")
    async def login(body: LoginInput, request: Request):
        ip = request.client.host
        recent = [t for t in failures.get(ip, []) if t > time.time() - 60]
        failures[ip] = recent
        if len(recent) >= 10:
            raise HTTPException(429, "Too many attempts. Wait one minute and try again.")
        username = os.environ.get("GOLDEN_USERNAME", "admin")
        password = os.environ.get("GOLDEN_PASSWORD", "admin")
        if not (hmac.compare_digest(body.username.encode(), username.encode()) and hmac.compare_digest(body.password.encode(), password.encode())):
            recent.append(time.time())
            raise HTTPException(401, "Incorrect username or password.")
        token = secrets.token_urlsafe(32)
        sessions[token] = time.time() + 12 * 3600
        response = JSONResponse({"ok": True})
        response.set_cookie("golden_session", token, httponly=True, samesite="strict", max_age=12 * 3600)
        return response

    @app.post("/api/logout")
    async def logout(request: Request):
        sessions.pop(request.cookies.get("golden_session"), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("golden_session")
        return response

    @app.get("/api/state")
    async def state():
        return {"connections": [store.public(c) for c in store.list("connections")],
                "conditions": store.list("conditions"), "profiles": store.list("profiles"),
                "files": [{k: v for k, v in f.items() if k != "path"} for f in store.list("files")],
                "attempts": [{k: a.get(k) for k in ("id", "file_id", "profile_id", "status", "input_tokens", "output_tokens", "cost", "score", "duration", "created_at")} | {"model": a["connection"]["model"], "provider": a["connection"]["provider"]} for a in store.list("attempts")]}

    @app.get("/api/folders")
    def folders(path: Optional[str] = None):
        return list_folders(path)

    @app.post("/api/folders")
    def new_folder(body: FolderInput):
        return create_folder(body.parent, body.name)

    def referenced_idle(kind, identity):
        for p in store.list("profiles"):
            if (kind == "connections" and p["connection_id"] == identity) or (kind == "conditions" and identity in p["condition_ids"]):
                engine.require_idle(p["id"])

    def delete_configuration(kind, identity):
        store.get(kind, identity)
        references = [p["name"] for p in store.list("profiles")
                      if (kind == "connections" and p["connection_id"] == identity)
                      or (kind == "conditions" and identity in p["condition_ids"])]
        if references:
            raise HTTPException(409, "Used by scan profile(s): " + ", ".join(references)
                                + ". Edit or delete those profiles before deleting this configuration.")
        store.delete(kind, identity)
        return {"ok": True}

    @app.delete("/api/connections/{identity}")
    async def delete_connection(identity: str):
        return delete_configuration("connections", identity)

    @app.delete("/api/conditions/{identity}")
    async def delete_condition(identity: str):
        return delete_configuration("conditions", identity)

    @app.delete("/api/profiles/{identity}")
    async def delete_profile(identity: str):
        try:
            return engine.delete_profile(identity)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post("/api/connections")
    @app.put("/api/connections/{identity}")
    async def save_connection(body: ConnectionInput, identity: Optional[str] = None):
        if body.provider not in llm.DEFAULT_URLS:
            raise ValueError("Choose a supported provider.")
        if not body.name.strip():
            raise ValueError("Enter a connection name.")
        existing = store.get("connections", identity) if identity else {}
        referenced_idle("connections", identity)
        value = body.model_dump(exclude={"api_key"})
        value["base_url"] = body.base_url.strip().rstrip("/") or llm.DEFAULT_URLS[body.provider]
        parsed = urlparse(value["base_url"])
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Enter a valid HTTP or HTTPS server address without embedded credentials.")
        if body.provider != "ollama" and parsed.scheme != "https":
            raise ValueError("Cloud LLM connections require HTTPS.")
        if body.provider != "ollama" and (parsed.hostname != urlparse(llm.DEFAULT_URLS[body.provider]).hostname or parsed.path not in {"", "/"}):
            raise ValueError("Use the provider's official server address. Use Local Ollama for a local server.")
        value["secret"] = store.seal(body.api_key.strip()) if body.api_key.strip() else existing.get("secret", "")
        if body.provider != "ollama" and not value["secret"]:
            raise ValueError("Enter an API key to configure this provider.")
        value["tested"] = False
        value["name"] = body.name.strip()
        return store.public(store.put("connections", {**existing, **value}))

    @app.post("/api/connections/{identity}/test")
    async def test(identity: str):
        connection = store.get("connections", identity)
        # Reject stale tests if settings were changed while the network call was in flight.
        version = connection["updated_at"]
        try:
            await llm.test_connection(connection, store.secret(connection))
        except Exception:
            if store.get("connections", identity)["updated_at"] == version:
                store.put("connections", {**connection, "tested": False})
            raise
        if store.get("connections", identity)["updated_at"] != version:
            raise ValueError("Connection changed while testing. Test it again.")
        store.put("connections", {**connection, "tested": True})
        return {"ok": True, "message": "Connection and model verified. No document was sent."}

    @app.post("/api/conditions")
    @app.put("/api/conditions/{identity}")
    async def save_condition(body: ConditionInput, identity: Optional[str] = None):
        referenced_idle("conditions", identity)
        existing = store.get("conditions", identity) if identity else {}
        texts = [c.strip() for c in body.conditions if c.strip()]
        if not body.name.strip() or not texts or any(len(c) > 5000 for c in texts):
            raise ValueError("Enter a name and at least one condition, up to 5,000 characters each.")
        if len(set(texts)) != len(texts):
            raise ValueError("Remove duplicate conditions so each criterion is counted once.")
        old = {c["text"]: c["id"] for c in existing.get("criteria", [])}
        return store.put("conditions", {**existing, "name": body.name.strip(), "criteria": [{"id": old.get(t, uid()), "text": t} for t in texts]})

    @app.post("/api/profiles")
    @app.put("/api/profiles/{identity}")
    async def save_profile(body: ProfileInput, identity: Optional[str] = None):
        if identity:
            engine.require_idle(identity)
        existing = store.get("profiles", identity) if identity else {}
        if not body.name.strip():
            raise ValueError("Enter a profile name.")
        store.get("connections", body.connection_id)
        condition_ids = list(dict.fromkeys(body.condition_ids))
        for c in condition_ids:
            store.get("conditions", c)
        source, target = Path(body.input_folder).expanduser(), Path(body.output_folder).expanduser()
        if not source.is_absolute() or not target.is_absolute():
            raise ValueError("Use absolute folder paths, for example /Users/you/Documents/input.")
        source, target = source.resolve(), target.resolve()
        if not source.is_dir():
            raise ValueError("Input folder must exist and be a directory.")
        if source == target or source in target.parents or target in source.parents:
            raise ValueError("Input and output folders must be separate; neither may contain the other.")
        target.mkdir(parents=True, exist_ok=True)
        value = {**body.model_dump(), "name": body.name.strip(), "condition_ids": condition_ids,
                 "input_folder": str(source), "output_folder": str(target)}
        reset = existing.get("input_folder") != str(source)
        if reset and identity:
            for f in engine.files(identity):
                store.put("files", {**f, "present": False})
        return store.put("profiles", {**existing, **value, "state": "draft" if reset else existing.get("state", "draft"),
                                      "warmed_at": None if reset else existing.get("warmed_at"), "notice": ""})

    @app.post("/api/profiles/{identity}/{action}")
    async def profile_action(identity: str, action: str):
        if action == "warm":
            await engine.warm(identity)
        elif action in {"start", "resume"}:
            await engine.start(identity)
        elif action == "rerun":
            await engine.start(identity, rerun=True)
        elif action == "pause":
            engine.pause(identity)
        else:
            raise HTTPException(404, "Unknown action")
        return {"ok": True}

    @app.get("/api/files/{identity}/report")
    async def report(identity: str):
        file = store.get("files", identity)
        return {"file": file, "attempts": [a for a in store.list("attempts") if a["file_id"] == identity]}

    @app.get("/api/files/{identity}/report/download")
    async def download_report(identity: str):
        data = await report(identity)
        return Response(json.dumps(data, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="report-{identity}.json"'})

    @app.post("/api/files/{identity}/retry")
    async def retry(identity: str):
        file = store.get("files", identity)
        engine.require_idle(file["profile_id"])
        if file["status"] not in {"error", "interrupted", "export_error"}:
            raise ValueError("Only failed or interrupted files can be retried.")
        if file["status"] == "export_error":
            attempt = store.get("attempts", file["last_attempt_id"])
            await asyncio.to_thread(engine.export, file, attempt)
        else:
            store.put("files", {**file, "status": "pending", "error": None})
        return {"ok": True}

    @app.get("/")
    async def index():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    return app
