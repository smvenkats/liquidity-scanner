import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

from execution.data.env import load_dotenv

load_dotenv()  # pick up QUESTRADE_REFRESH_TOKEN from project-root .env if present

_HAS_TOKEN = bool(os.environ.get("QUESTRADE_REFRESH_TOKEN")) or \
    (Path(__file__).resolve().parents[1] / ".questrade_token.json").exists()


@pytest.mark.skipif(not _HAS_TOKEN, reason="no Questrade token configured")
def test_live_fetch_recent_spy_5m():
    from execution.data.questrade_client import QuestradeClient, QuestradeAuthError, QuestradeAPIError
    from execution.data.backfill import fetch_series_questrade
    from execution.config import load_params

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=3)
    try:
        rows, gaps = fetch_series_questrade(QuestradeClient(), "SPY", "5m", start, end, load_params())
    except (QuestradeAuthError, QuestradeAPIError) as e:
        pytest.skip(f"Questrade not reachable/authed (token likely rotated or expired): {e}")
    assert rows, "expected some recent SPY 5m bars"
    tss = [r["ts"] for r in rows]
    assert tss == sorted(tss), "bars must be ascending"
    assert set(rows[0]) == {"ts", "o", "h", "l", "c", "v"}
