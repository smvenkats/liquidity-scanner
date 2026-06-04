from __future__ import annotations


def summarize(trades) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "expectancy_r": 0.0,
                "profit_factor": 0.0, "avg_bars_held": 0.0}
    # breakeven (r==0) counts as a non-win
    wins = [t.r_multiple for t in trades if t.r_multiple > 0]
    losses = [t.r_multiple for t in trades if t.r_multiple <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "n": n,
        "win_rate": len(wins) / n,
        "expectancy_r": sum(t.r_multiple for t in trades) / n,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "avg_bars_held": sum(t.bars_held for t in trades) / n,
    }


def slice_by(trades, keyfn) -> dict:
    groups: dict = {}
    for t in trades:
        groups.setdefault(keyfn(t), []).append(t)
    return {k: summarize(v) for k, v in groups.items()}
