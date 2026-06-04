# dashboard/server.py
from __future__ import annotations
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from execution.backtest.store import BarStore
from dashboard.feed import load_signals, JsonlTailer, bars_window

SIGNALS_PATH = Path(os.environ.get("SIGNALS_PATH", ".tmp/signals.jsonl"))
BARS_DIR = os.environ.get("BARS_DIR", ".tmp/bt_data")
STATIC = Path(__file__).parent / "static"
POLL_SECONDS = float(os.environ.get("DASH_POLL_SECONDS", "1.0"))


def make_app() -> FastAPI:
    store = BarStore(BARS_DIR)
    clients: set = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tailer = JsonlTailer(SIGNALS_PATH)
        tailer.new_records()   # consume existing (already sent as backlog on connect)

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

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    @app.get("/bars")
    async def bars(symbol: str, ts: str):
        w = bars_window(store, symbol, datetime.fromisoformat(ts))
        return JSONResponse({"symbol": symbol, "bars": [
            {"ts": b.ts.isoformat(), "o": b.o, "h": b.h, "l": b.l, "c": b.c, "v": b.v}
            for b in w]})

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
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
