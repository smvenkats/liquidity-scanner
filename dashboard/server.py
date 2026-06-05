# dashboard/server.py
from __future__ import annotations
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import json
from datetime import datetime, timezone
import threading
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from execution.backtest.store import BarStore
from dashboard.feed import load_signals, JsonlTailer, bars_window
from dashboard.auth import require_auth, check_basic, auth_enabled
from dashboard.scheduler import start_scheduler

SIGNALS_PATH = Path(os.environ.get("SIGNALS_PATH", ".tmp/signals.jsonl"))
BARS_DIR = os.environ.get("BARS_DIR", ".tmp/bt_data")
STATIC = Path(__file__).parent / "static"
POLL_SECONDS = float(os.environ.get("DASH_POLL_SECONDS", "1.0"))


def make_app() -> FastAPI:
    # Fail closed in production: never serve an internet-facing dashboard without auth.
    # RAILWAY_ENVIRONMENT is always injected by Railway; local/tests are unaffected.
    if os.environ.get("RAILWAY_ENVIRONMENT") and not auth_enabled():
        raise RuntimeError("Refusing to serve without auth: set DASH_USER and DASH_PASSWORD.")
    store = BarStore(BARS_DIR)
    clients: set = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tailer = JsonlTailer(SIGNALS_PATH)
        tailer.new_records()   # consume existing (already sent as backlog on connect)
        stop = threading.Event()
        start_scheduler(stop)  # periodic scan -> appends to SIGNALS_PATH (no-op if SCAN_ENABLED=false)

        async def loop():
            while True:
                try:
                    for rec in tailer.new_records():
                        for c in list(clients):
                            try:
                                await c.send_json({"type": "signal", "signal": rec})
                            except Exception:
                                clients.discard(c)
                except Exception:
                    pass   # one bad poll must never kill streaming
                await asyncio.sleep(POLL_SECONDS)

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            stop.set()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", dependencies=[Depends(require_auth)])
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/bars", dependencies=[Depends(require_auth)])
    async def bars(symbol: str, ts: str):
        w = bars_window(store, symbol, datetime.fromisoformat(ts))
        return JSONResponse({"symbol": symbol, "bars": [
            {"ts": b.ts.isoformat(), "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v}
            for b in w]})

    @app.post("/test-signal", dependencies=[Depends(require_auth)])
    async def test_signal():
        from execution.scanner.emit_test_signal import make_test_signal
        sig = make_test_signal(datetime.now(timezone.utc))
        SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SIGNALS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sig) + "\n")
        return JSONResponse({"ok": True, "signal_id": sig["signal_id"]})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        if not check_basic(websocket.headers.get("authorization")):
            await websocket.close(code=1008)  # policy violation — unauthorized
            return
        await websocket.accept()
        clients.add(websocket)
        await websocket.send_json({"type": "backlog", "signals": load_signals(SIGNALS_PATH)})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            clients.discard(websocket)

    return app


app = make_app()
