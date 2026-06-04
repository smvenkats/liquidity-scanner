# Dashboard (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. NOTE: Task 5 (visual verification) is performed by the CONTROLLER with the Preview tools, not the implementer subagent.

**Goal:** A single-page web dashboard — filter panel (left), live signal table (center), inline SVG sparkline preview (right) — that streams QUALIFIED signals over WebSocket from a lightweight Python backend reading the `signals.jsonl` stream.

**Architecture:** A small FastAPI app serves one static `index.html` (vanilla HTML/CSS/JS — no build step), a `/bars` endpoint (recent 5m bars for the sparkline, from `BarStore`), and a `/ws` WebSocket that sends the current signal backlog on connect then streams new lines as `signals.jsonl` grows. All backend logic (load, tail, bars-window, server routes) is unit-tested; the frontend is verified visually.

**Tech Stack:** Python 3.11+, `fastapi`, `uvicorn[standard]`, `pytest`, `httpx` (FastAPI TestClient). Frontend: plain HTML/CSS/JS, zero dependencies.

---

## ⚠️ Commit policy
No new `git commit` during these tasks. Checkpoint = green tests + a visual confirmation. We commit once after sign-off.

## Decisions (locked)
- **Frontend:** one self-contained `dashboard/static/index.html` (vanilla). No node/build.
- **Chart preview:** inline SVG sparkline of recent 5m closes + horizontal marks for level / entry / stop / target and a dot at the sweep wick.
- **Backend:** FastAPI + uvicorn; serves static + `/bars` + `/ws`. Signal source = tail `signals.jsonl` (the Phase 3 sink output). Bars source = `BarStore` over a data dir.
- **Filtering** is client-side (the filter panel) over the in-memory signal list.

## File structure
| File | Responsibility |
|---|---|
| `dashboard/__init__.py` | package marker (empty) |
| `dashboard/feed.py` | `load_signals`, `JsonlTailer`, `bars_window` (pure, tested) |
| `dashboard/server.py` | `make_app()` FastAPI: `/`, `/bars`, `/ws` |
| `dashboard/static/index.html` | the vanilla SPA |
| `.claude/launch.json` | Preview config to run the server |
| `directives/run_dashboard.md` | SOP (final task) |
| `tests/test_dash_feed.py`, `tests/test_dash_server.py` | tests |

---

### Task 1: Scaffolding + deps

**Files:**
- Create: `dashboard/__init__.py` (empty)
- Modify: `requirements.txt`

- [ ] **Step 1: Add deps to `requirements.txt`** (append)

```
fastapi>=0.110
uvicorn[standard]>=0.29
httpx>=0.27
```

- [ ] **Step 2: Install + create the package marker**

Create empty `dashboard/__init__.py`. Run: `pip install -r requirements.txt`
Expected: fastapi, uvicorn, httpx install successfully.

- [ ] **Step 3: Verify import**

Run: `python -c "import fastapi, uvicorn, httpx; import dashboard; print('ok')"`
Expected: prints `ok`.

---

### Task 2: Feed helpers (load / tail / bars-window)

**Files:**
- Create: `dashboard/feed.py`
- Test: `tests/test_dash_feed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dash_feed.py
import json
from datetime import datetime, timedelta
from execution.models import Bar
from dashboard.feed import load_signals, JsonlTailer, bars_window

def test_load_signals_reads_jsonl_and_handles_missing(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"symbol":"A","rr":3}\n{"symbol":"B","rr":4}\n')
    got = load_signals(p)
    assert [g["symbol"] for g in got] == ["A", "B"]
    assert load_signals(tmp_path / "nope.jsonl") == []

def test_jsonl_tailer_yields_only_new_complete_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"n":1}\n{"n":2}\n')
    t = JsonlTailer(p)
    assert [r["n"] for r in t.new_records()] == [1, 2]
    assert t.new_records() == []                      # nothing new
    with p.open("a") as f:
        f.write('{"n":3}\n{"n":4}')                   # last line has no newline yet
    assert [r["n"] for r in t.new_records()] == [3]   # only the complete line
    with p.open("a") as f:
        f.write('\n')                                 # complete line 4
    assert [r["n"] for r in t.new_records()] == [4]

def _b(ts, c):
    return Bar(ts=ts, o=c, h=c, l=c, c=c, v=1)

class _Store:
    def __init__(self, bars): self._bars = bars
    def bars(self, sym, tf): return self._bars

def test_bars_window_slices_around_center():
    base = datetime(2026, 6, 4, 13, 30)
    bars = [_b(base + timedelta(minutes=5 * i), 100 + i) for i in range(30)]
    w = bars_window(_Store(bars), "X", base + timedelta(minutes=5 * 20), before=4, after=2)
    assert [round(b.c) for b in w] == [116, 117, 118, 119, 120, 121, 122]  # idx16..22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dash_feed.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.feed'`

- [ ] **Step 3: Write minimal implementation**

```python
# dashboard/feed.py
from __future__ import annotations
import json
from pathlib import Path
from execution.models import Bar


def load_signals(path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


class JsonlTailer:
    """Returns records appended to a JSONL file since the last call. Only complete
    (newline-terminated) lines are consumed; a partial trailing line is held back."""

    def __init__(self, path):
        self.path = Path(path)
        self._seen = 0

    def new_records(self) -> list[dict]:
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        lines = text.splitlines()
        complete = lines if text.endswith("\n") else lines[:-1]
        fresh = complete[self._seen:]
        self._seen = len(complete)
        return [json.loads(s) for s in (x.strip() for x in fresh) if s]


def bars_window(store, symbol, center_ts, before=12, after=6) -> list[Bar]:
    bars = store.bars(symbol, "5m")
    idx = None
    for i, b in enumerate(bars):
        if b.ts <= center_ts:
            idx = i
        else:
            break
    if idx is None:
        return []
    return bars[max(0, idx - before): idx + after + 1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dash_feed.py -q`
Expected: PASS (3 passed)

---

### Task 3: FastAPI server

**Files:**
- Create: `dashboard/server.py`
- Test: `tests/test_dash_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dash_server.py
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import dashboard.server as server

def _seed_static(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><body>dash</body></html>", encoding="utf-8")
    return static

def _seed_bars(tmp_path):
    rows = [{"ts": (datetime(2026, 6, 4, 13, 30) + timedelta(minutes=5 * i)).isoformat(),
             "o": 100 + i, "h": 100 + i, "l": 100 + i, "c": 100 + i, "v": 1} for i in range(10)]
    (tmp_path / "X_5m.json").write_text(json.dumps(rows))
    return tmp_path

def test_index_and_bars_and_backlog(tmp_path, monkeypatch):
    static = _seed_static(tmp_path)
    bars_dir = tmp_path / "data"; bars_dir.mkdir()
    _seed_bars(bars_dir)
    sig = tmp_path / "signals.jsonl"
    sig.write_text('{"symbol":"X","rr":3,"qualified":true}\n')

    monkeypatch.setattr(server, "STATIC", static)
    monkeypatch.setattr(server, "BARS_DIR", str(bars_dir))
    monkeypatch.setattr(server, "SIGNALS_PATH", sig)
    app = server.make_app()
    client = TestClient(app)

    assert "dash" in client.get("/").text                      # serves index.html
    ts = (datetime(2026, 6, 4, 13, 30) + timedelta(minutes=25)).isoformat()
    body = client.get(f"/bars?symbol=X&ts={ts}").json()
    assert body["symbol"] == "X" and len(body["bars"]) >= 1     # bars window

    with client.websocket_connect("/ws") as ws:                # backlog on connect
        msg = ws.receive_json()
        assert msg["type"] == "backlog" and msg["signals"][0]["symbol"] == "X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dash_server.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'dashboard.server'`

- [ ] **Step 3: Write minimal implementation**

```python
# dashboard/server.py
from __future__ import annotations
import os
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from execution.backtest.store import BarStore
from dashboard.feed import load_signals, JsonlTailer, bars_window

SIGNALS_PATH = Path(os.environ.get("SIGNALS_PATH", ".tmp/signals.jsonl"))
BARS_DIR = os.environ.get("BARS_DIR", ".tmp/bt_data")
STATIC = Path(__file__).parent / "static"


def make_app() -> FastAPI:
    app = FastAPI()
    store = BarStore(BARS_DIR)
    clients: set = set()

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

    @app.on_event("startup")
    async def _tail():
        tailer = JsonlTailer(SIGNALS_PATH)
        tailer.new_records()   # consume existing (already sent as backlog)

        async def loop():
            while True:
                for rec in tailer.new_records():
                    for c in list(clients):
                        try:
                            await c.send_json({"type": "signal", "signal": rec})
                        except Exception:
                            clients.discard(c)
                await asyncio.sleep(1)

        asyncio.create_task(loop())

    return app


app = make_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dash_server.py -q`
Expected: PASS (1 passed)

---

### Task 4: Frontend SPA (build — visual verify in Task 5)

**Files:**
- Create: `dashboard/static/index.html`

- [ ] **Step 1: Write the single-file dashboard**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Liquidity Sweep Scanner</title>
<style>
  :root{--bg:#0e1116;--panel:#161b22;--line:#2d333b;--txt:#c9d1d9;--muted:#8b949e;--long:#2ea043;--short:#f85149;--accent:#58a6ff}
  *{box-sizing:border-box}
  body{margin:0;font:13px/1.4 ui-monospace,Menlo,Consolas,monospace;background:var(--bg);color:var(--txt);height:100vh;display:grid;grid-template-columns:230px 1fr 360px}
  .panel{background:var(--panel);overflow:auto;border-right:1px solid var(--line)}
  h2{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:14px 12px 6px}
  .ctl{display:flex;justify-content:space-between;align-items:center;padding:5px 12px}
  .ctl label{color:var(--muted)}
  .ctl input,.ctl select{background:#0e1116;color:var(--txt);border:1px solid var(--line);border-radius:5px;padding:3px 6px;width:96px}
  #status{padding:8px 12px;color:var(--muted);border-top:1px solid var(--line);position:sticky;bottom:0;background:var(--panel)}
  table{width:100%;border-collapse:collapse}
  th,td{padding:6px 8px;text-align:right;white-space:nowrap}
  th{position:sticky;top:0;background:#1b2129;color:var(--muted);border-bottom:1px solid var(--line)}
  td:first-child,th:first-child,td:nth-child(2),th:nth-child(2){text-align:left}
  tbody tr{border-bottom:1px solid var(--line);cursor:pointer}
  tbody tr:hover{background:#1b2129}
  tr.sel{background:#1f2630}
  .long{color:var(--long)} .short{color:var(--short)}
  .badge{font-size:10px;padding:1px 5px;border-radius:8px;background:var(--accent);color:#0e1116;margin-left:6px}
  @keyframes flash{from{background:#1d3326}to{background:transparent}}
  tr.new{animation:flash 6s ease-out}
  #preview{padding:12px;border-right:none}
  #pvhead{color:var(--muted);margin:6px 0 8px}
  svg{width:100%;height:210px;background:#0e1116;border:1px solid var(--line);border-radius:6px}
  .empty{color:var(--muted);padding:20px;text-align:center}
</style>
</head>
<body>
<div class="panel" id="filters">
  <h2>Filters</h2>
  <div class="ctl"><label>Min R:R</label><input id="f_rr" type="number" step="0.5" value="2"/></div>
  <div class="ctl"><label>Min |RS| %</label><input id="f_rs" type="number" step="0.1" value="0"/></div>
  <div class="ctl"><label>Direction</label><select id="f_dir"><option value="">both</option><option>long</option><option>short</option></select></div>
  <div class="ctl"><label>Level</label><select id="f_lvl"><option value="">any</option><option>PDL</option><option>PDH</option></select></div>
  <div class="ctl"><label>Killzone</label><select id="f_kz"><option value="">any</option><option>ny_open</option><option>power_hour</option><option>midday</option></select></div>
  <div class="ctl"><label>Max age min</label><input id="f_age" type="number" step="5" value="0" title="0 = no limit"/></div>
  <h2>Legend</h2>
  <div class="ctl"><span class="long">&#9650; long</span><span class="short">&#9660; short</span></div>
</div>
<div class="panel" id="center">
  <h2>Qualified signals (<span id="count">0</span>)</h2>
  <table>
    <thead><tr><th>time</th><th>ticker</th><th>dir</th><th>lvl</th><th>entry</th><th>stop</th><th>target</th><th>R:R</th><th>RS%</th><th>spr</th><th>rvol</th><th>kz</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div id="empty" class="empty">waiting for signals&#8230;</div>
  <div id="status">connecting&#8230;</div>
</div>
<div class="panel" id="preview">
  <h2>Preview</h2>
  <div id="pvhead">select a signal</div>
  <svg id="spark" viewBox="0 0 360 210" preserveAspectRatio="none"></svg>
</div>
<script>
const S=[]; let selected=null;
const $=id=>document.getElementById(id);
const fnum=(x,d=2)=>(x==null||x===''?'':Number(x).toFixed(d));
const tstr=iso=>{try{return new Date(iso).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}catch(e){return iso;}};
function passes(s){
  const rr=+$('f_rr').value||0, rs=+$('f_rs').value||0, dir=$('f_dir').value, lvl=$('f_lvl').value, kz=$('f_kz').value, age=+$('f_age').value||0;
  if((s.rr||0)<rr) return false;
  if(Math.abs((s.rs_score||0)*100)<rs) return false;
  if(dir&&s.direction!==dir) return false;
  if(lvl&&s.level_type!==lvl) return false;
  if(kz&&s.killzone!==kz) return false;
  if(age>0){const m=(Date.now()-new Date(s.reentry_time).getTime())/60000; if(m>age) return false;}
  return true;
}
function render(){
  const rows=$('rows'); rows.innerHTML='';
  const vis=S.filter(passes);
  $('count').textContent=vis.length;
  $('empty').style.display=vis.length?'none':'block';
  for(const s of vis){
    const tr=document.createElement('tr');
    tr.className=(s._new?'new ':'')+(selected===s.signal_id?'sel':'');
    const dc=s.direction==='long'?'long':'short', arr=s.direction==='long'?'&#9650;':'&#9660;';
    tr.innerHTML=`<td>${tstr(s.reentry_time)}${s._new?'<span class="badge">new</span>':''}</td>`+
      `<td>${s.symbol}</td><td class="${dc}">${arr}</td><td>${s.level_type}</td>`+
      `<td>${fnum(s.entry_price)}</td><td>${fnum(s.stop_price)}</td><td>${fnum(s.target_price)}</td>`+
      `<td>${fnum(s.rr,1)}</td><td class="${(s.rs_score>=0)?'long':'short'}">${fnum((s.rs_score||0)*100,2)}</td>`+
      `<td>${fnum(s.spread_bps,1)}</td><td>${fnum((s.volume_context||{}).rvol,1)}</td><td>${s.killzone||''}</td>`;
    tr.onclick=()=>{selected=s.signal_id; render(); preview(s);};
    rows.appendChild(tr);
  }
}
async function preview(s){
  $('pvhead').innerHTML=`<b>${s.symbol}</b> ${s.direction} ${s.level_type} &#183; R:R ${fnum(s.rr,1)} &#183; ${tstr(s.reentry_time)}`;
  let bars=[];
  try{const r=await fetch(`/bars?symbol=${encodeURIComponent(s.symbol)}&ts=${encodeURIComponent(s.reentry_time)}`); bars=(await r.json()).bars||[];}catch(e){}
  drawSpark(s,bars);
}
function drawSpark(s,bars){
  const svg=$('spark'),W=360,H=210,pad=10;
  if(!bars.length){svg.innerHTML='<text x="12" y="24" fill="#8b949e">no bar data</text>';return;}
  const cs=bars.map(b=>b.c), marks=[s.level_price,s.entry_price,s.stop_price,s.target_price,s.wick_extreme].filter(x=>x!=null);
  const lo=Math.min(...cs,...marks), hi=Math.max(...cs,...marks), span=(hi-lo)||1;
  const x=i=>pad+i*(W-2*pad)/Math.max(1,bars.length-1);
  const y=v=>pad+(H-2*pad)*(1-(v-lo)/span);
  const path=cs.map((c,i)=>`${i?'L':'M'}${x(i).toFixed(1)} ${y(c).toFixed(1)}`).join(' ');
  const hl=(v,col,dash='')=>v==null?'':`<line x1="0" y1="${y(v).toFixed(1)}" x2="${W}" y2="${y(v).toFixed(1)}" stroke="${col}" stroke-width="1" stroke-dasharray="${dash}"/>`;
  let wi=bars.findIndex(b=>b.l<=s.wick_extreme&&b.h>=s.wick_extreme); if(wi<0) wi=0;
  svg.innerHTML=hl(s.level_price,'#8b949e','4 3')+hl(s.target_price,'#2ea043','2 2')+hl(s.stop_price,'#f85149','2 2')+hl(s.entry_price,'#58a6ff')+
    `<path d="${path}" fill="none" stroke="#c9d1d9" stroke-width="1.5"/>`+
    `<circle cx="${x(wi).toFixed(1)}" cy="${y(s.wick_extreme).toFixed(1)}" r="3.5" fill="#d29922"/>`;
}
function add(sig,isNew){sig._new=!!isNew; S.unshift(sig); if(isNew) setTimeout(()=>{sig._new=false; render();},6000);}
function connect(){
  const ws=new WebSocket(`ws://${location.host}/ws`);
  ws.onopen=()=>$('status').textContent='● live · connected';
  ws.onclose=()=>{$('status').textContent='disconnected — retrying…'; setTimeout(connect,2000);};
  ws.onmessage=ev=>{const m=JSON.parse(ev.data);
    if(m.type==='backlog') m.signals.forEach(x=>add(x,false));
    else if(m.type==='signal') add(m.signal,true);
    render();
  };
}
['f_rr','f_rs','f_dir','f_lvl','f_kz','f_age'].forEach(id=>$(id).addEventListener('input',render));
connect(); render();
</script>
</body>
</html>
```

- [ ] **Step 2: Confirm the file exists and is non-trivial**

Run: `python -c "import pathlib; t=pathlib.Path('dashboard/static/index.html').read_text(); assert 'WebSocket' in t and 'spark' in t and len(t)>2000; print('ok', len(t))"`
Expected: prints `ok <len>` (no visual check here — that's Task 5).

---

### Task 5: Launch config + live visual verification (CONTROLLER)

**Files:**
- Create: `.claude/launch.json`

- [ ] **Step 1: Create `.claude/launch.json`**

```json
{
  "version": "0.0.1",
  "configurations": [
    {
      "name": "dashboard",
      "runtimeExecutable": "python",
      "runtimeArgs": ["-m", "uvicorn", "dashboard.server:app", "--port", "8787"],
      "port": 8787
    }
  ]
}
```

- [ ] **Step 2 (controller): seed demo signals**

Generate a few real signals into the path the server reads (default `.tmp/signals.jsonl`) — e.g. reuse `.tmp/live_demo_fire.py` (the as-of-2026-06-02 gate-off run) so the table has rows whose symbols exist in `.tmp/bt_data` (so `/bars` sparklines resolve). Confirm `.tmp/signals.jsonl` is non-empty.

- [ ] **Step 3 (controller): start + screenshot**

Use the Preview tools: `preview_start("dashboard")`, then `preview_screenshot` / `preview_snapshot`. Verify: three-pane layout renders; the signal table shows the seeded rows with correct dir colors and R:R; clicking a row populates the right-pane sparkline with the price line + level/entry/stop/target marks + wick dot. Use `preview_console_logs` (level error) to confirm no JS errors and `preview_inspect` to confirm the WS status reads "live · connected".

- [ ] **Step 4 (controller): live-update check**

Append one more signal line to `.tmp/signals.jsonl` while the page is open; within ~1–2s confirm a new row appears at the top with the "new" badge + flash animation (the tail loop → WS push path).

---

### Task 6: Directive + full-suite checkpoint

**Files:**
- Create: `directives/run_dashboard.md`
- Test: none

- [ ] **Step 1: Create the directive**

```markdown
# Directive: Run the Dashboard

**Goal:** Watch QUALIFIED signals live in the browser.

**Tools:** `dashboard/server.py` (FastAPI). Env: `SIGNALS_PATH` (default `.tmp/signals.jsonl`), `BARS_DIR` (default `.tmp/bt_data`).

**Steps:**
1. Ensure the scanner is writing signals to `SIGNALS_PATH` (Phase 3 `emit_signals`).
2. Start: `python -m uvicorn dashboard.server:app --port 8787` (from the project root).
3. Open `http://localhost:8787`. The table streams signals; click a row for the sparkline.

**Notes:**
- Filtering is client-side. The `/bars` sparkline needs the symbol's 5m file in `BARS_DIR`.
- Signal-only display; no order actions here (execution = Phase 5).
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: PASS — Phase 1-3 (72) + Phase 4 (4) = **76 passed**, 0 failed.
(Phase 4 pytest: feed 3, server 1. The frontend is verified visually in Task 5, not via pytest.)

- [ ] **Step 3: Report (no commit)**

Summarize backend modules + green count; confirm the dashboard was visually verified (screenshot) and streams live; note we hold git until sign-off.

---

## Self-Review

**1. Spec coverage** (vs dashboard sections of the design spec):
- Filter panel (min RS, min R:R, time-of-day, direction, level) → `index.html` filters ✅
- Center table (ticker, dir, time, level, entry/stop/target, R:R, RS, spread, volume) → table ✅
- Right sparkline w/ marked level + wick sweep → `drawSpark` ✅
- Real-time WebSocket updates + new-signal highlight → `/ws` + `flash` animation + badge ✅
- Backend: serves signals as JSON, WS push, bars for preview → `server.py` ✅
- *Deferred intentionally:* TradingView full-chart on click (chose sparkline), server-side filtering (client-side per spec), auth. Not gaps.

**2. Placeholder scan:** No TBD/TODO. Frontend is complete inline.

**3. Type consistency:** `load_signals`/`JsonlTailer`/`bars_window` (Task 2) consumed by `server.py` (Task 3) with matching signatures. Frontend reads the exact signal fields emitted by Phase 3 `Signal.to_dict()` (`reentry_time`, `entry_price`, `stop_price`, `target_price`, `rr`, `rs_score`, `spread_bps`, `volume_context.rvol`, `level_price`, `wick_extreme`, `killzone`, `level_type`, `direction`, `symbol`, `signal_id`). `/bars` returns `{ts,o,h,l,c,v}` which the sparkline reads via `.c`.

---

## Post-review hardening (applied; suite → 78, frontend visually verified)
Code-quality review (CHANGES-REQUESTED) drove these robustness fixes:
- **Malformed-line tolerance** — `load_signals` / `JsonlTailer.new_records` skip bad JSON instead of raising (a single corrupt line no longer kills streaming for all clients).
- **Server modernized** — `on_event` → `lifespan` (task cancelled on shutdown, deprecation warnings gone); tail loop body guarded; `DASH_POLL_SECONDS` configurable.
- **Frontend dedup** by `signal_id` in `add()` — closes the narrow backlog/tail double-send race.
- +2 tests (malformed lines; the WS *streaming* path via `with TestClient` + low poll interval). Directive notes the append-only/rotation assumption.
- **Visual verification (controller):** 3-pane render, live WS, row→sparkline via `/bars`, and live append→push all confirmed; no console errors.

## Next
- **Phase 5:** execution seam — qualified signal → `stage_order` → `check_compliance_limits` → `place_order_live` on the existing tv-mcp rails (approval-gated). This is where the Questrade reauth becomes required.
- **Live driver:** a scheduled `scan_once` loop writing `signals.jsonl` so the dashboard streams genuinely live during RTH.
