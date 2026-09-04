from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import auth, capture, input as remote_input
from app.paths import STATIC_DIR

COOKIE = "pc_remote"
PORT = 8765
BIND_HOST = "127.0.0.1"

sessions: set[str] = set()
clients: set[WebSocket] = set()
screen = (0, 0, 1, 1)


def _authed(request: Request) -> bool:
    return request.cookies.get(COOKIE) in sessions


def create_app() -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page() -> str:
        return (STATIC_DIR / "login.html").read_text(encoding="utf-8")

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        body = await request.json()
        password = str(body.get("password") or "")
        if not auth.password_ok(password):
            return JSONResponse({"ok": False}, status_code=403)
        token = auth.new_session()
        sessions.add(token)
        response = JSONResponse({"ok": True})
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 12,
            path="/",
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        if not _authed(request):
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        token = socket.cookies.get(COOKIE)
        if token not in sessions:
            await socket.close(code=4401)
            return
        await socket.accept()
        clients.add(socket)
        try:
            while True:
                raw = await socket.receive_text()
                _handle_event(json.loads(raw))
        except (WebSocketDisconnect, json.JSONDecodeError):
            pass
        finally:
            clients.discard(socket)

    @app.on_event("startup")
    async def startup() -> None:
        global screen
        screen = capture.virtual_screen()
        asyncio.create_task(_broadcast())

    return app


def _handle_event(payload: dict[str, Any]) -> None:
    kind = str(payload.get("t") or "")
    if kind == "move":
        remote_input.move_mouse(float(payload["x"]), float(payload["y"]), screen)
        return
    if kind == "down":
        remote_input.mouse_button(
            float(payload["x"]),
            float(payload["y"]),
            int(payload.get("b") or 0),
            True,
            screen,
        )
        return
    if kind == "up":
        remote_input.mouse_button(
            float(payload["x"]),
            float(payload["y"]),
            int(payload.get("b") or 0),
            False,
            screen,
        )
        return
    if kind == "wheel":
        remote_input.mouse_wheel(int(payload.get("d") or 0))
        return
    if kind == "key":
        remote_input.key_event(str(payload.get("c") or ""), bool(payload.get("d")))


async def _broadcast() -> None:
    loop = asyncio.get_running_loop()
    while True:
        if not clients:
            await asyncio.sleep(0.2)
            continue
        jpeg = await loop.run_in_executor(None, capture.grab_jpeg)
        dead: list[WebSocket] = []
        for socket in list(clients):
            try:
                await socket.send_bytes(jpeg)
            except Exception:
                dead.append(socket)
        for socket in dead:
            clients.discard(socket)
        await asyncio.sleep(0.12)
