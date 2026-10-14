"""A minimal web front end for the demo. SIMULATION ONLY.

    uv run python -m wali.interfaces.web

One static chat page and a small JSON API. The role is picked in the page, as a stand-in for
logging in, exactly like ``/role`` in the CLI. That means anyone who can reach the server can act
as the owner, so it listens on this computer only unless told otherwise.

Confirmation tokens never leave the server: the page names a request by its id, and the guard
checks the role again when it is confirmed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from wali.app import SetupError, WaliApp, build_app
from wali.config import ConfigError, load_settings
from wali.interfaces.common import SIMULATION_NOTE, draft_demo_mandate, request_view
from wali.models import Principal
from wali.tools.base import ToolFailure

CHANNEL = "web"
STATIC = Path(__file__).with_name("static")
MAX_MESSAGE_CHARS = 4000
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

Role = Literal["owner", "bookkeeper", "staff"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


class ChatBody(_Body):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class RequestBody(_Body):
    subject_id: str = Field(min_length=1, max_length=100)


def create_web_app(wali: WaliApp, principals: Mapping[str, Principal]) -> FastAPI:
    """The FastAPI application. ``principals`` maps each role the page offers to the user it
    acts as."""
    api = FastAPI(title="Wali (simulation)", docs_url=None, redoc_url=None, openapi_url=None)

    def principal(role: str) -> Principal:
        found = principals.get(role)
        if found is None:
            raise HTTPException(404, f"No {role} in this business.")
        return found

    @api.middleware("http")
    async def guard_requests(request: Request, call_next):
        # Another website open in the same browser may not drive this one: a changing request
        # must be JSON (which a plain cross-site form cannot send) from this page's own origin.
        if request.method not in ("GET", "HEAD"):
            content_type = request.headers.get("content-type", "").split(";")[0].strip()
            origin = request.headers.get("origin")
            same_origin = origin is None or origin == f"{request.url.scheme}://{request.url.netloc}"
            if content_type != "application/json" or not same_origin:
                return JSONResponse({"detail": "Refused."}, status_code=403)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @api.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @api.get("/api/info")
    def info() -> dict:
        return {
            "simulation": SIMULATION_NOTE,
            "roles": [role for role in ("owner", "bookkeeper", "staff") if role in principals],
            "screening_model": wali.sentinel_model_enabled,
        }

    @api.post("/api/chat")
    def chat(body: ChatBody) -> dict:
        result = wali.chat(principal(body.role), body.text, channel=CHANNEL)
        return {
            "reply": result.reply.text,
            "blocked": result.reply.blocked,
            "new_requests": [request_view(r) for r in result.new_confirmations],
        }

    @api.get("/api/pending")
    def pending(role: Role) -> dict:
        return {"requests": [request_view(r) for r in wali.pending(principal(role))]}

    @api.post("/api/confirm")
    def confirm(body: RequestBody) -> dict:
        decision = wali.confirm(principal(body.role), channel=CHANNEL, subject_id=body.subject_id)
        if decision is None:
            raise HTTPException(404, "Nothing with that id is waiting for you.")
        return {"status": decision.status, "message": decision.user_message}

    @api.post("/api/cancel")
    def cancel(body: RequestBody) -> dict:
        if not wali.cancel(principal(body.role), channel=CHANNEL, subject_id=body.subject_id):
            raise HTTPException(404, "Nothing with that id is waiting for you.")
        return {"status": "declined", "message": "Declined. Nothing was paid or changed."}

    @api.post("/api/mandate")
    def mandate(body: _Body) -> dict:
        if body.role != "owner":
            raise HTTPException(403, "Only the owner can set the mandate.")
        try:
            decision = draft_demo_mandate(wali, principal(body.role))
        except (PermissionError, ToolFailure):
            raise HTTPException(
                503, "The mandate could not be drafted. Please try again."
            ) from None
        return {"status": decision.status, "message": decision.user_message}

    @api.post("/api/reset")
    def reset(body: _Body) -> dict:
        wali.reset(principal(body.role), channel=CHANNEL)
        return {"status": "reset"}

    api.mount("/static", StaticFiles(directory=STATIC), name="static")
    return api


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Wali demo web page (simulation only).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        wali = build_app(load_settings())
    except (SetupError, ConfigError) as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1
    if args.host not in LOCAL_HOSTS:
        print(
            f"WARNING: listening on {args.host}. The page has no login: anyone who can reach "
            "it can act as the owner.",
            file=sys.stderr,
        )
    import uvicorn

    print(f"{SIMULATION_NOTE} Open http://{args.host}:{args.port}/")
    uvicorn.run(create_web_app(wali, wali.env.principals()), host=args.host, port=args.port)
    return 0
