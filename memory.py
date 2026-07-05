"""
Memory module — Final Polish
Richer performance context fed back into the AI prompt each cycle,
including hot/cold streaks per signal type and recent win rate trend.
"""

import json
import logging
import os

log = logging.getLogger("memory")

MEMORY_FILE = "memory.json"

TAGS = [
    "RSI oversold", "RSI overbought", "RSI <", "RSI >",
    "MACD+", "MACD-", "MACD bearish", "MACD bullish",
    "MACD bullish crossover", "MACD bearish crossover",
    "EMA20>EMA50", "EMA20<EMA50", "price>EMA20", "price<EMA20",
    "UPTREND", "DOWNTREND",
    "BULLISH ENGULFING", "BEARISH ENGULFING",
    "HAMMER", "MORNING STAR", "EVENING STAR", "SHOOTING STAR",
    "THREE GREEN", "THREE RED",
    "Rule engine",
    "breakout", "resistance", "support",
]


def load_state() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {}
    try:
        with open(MEMORY_FILE) as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Could not load memory file: {e}")
        return {}


def save_state(trader) -> None:
    try:
        data = trader.export_state()
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, default=str)
    except Exception as e:
        log.warning(f"Could not save memory file: {e}")


def load_into_trader(trader) -> None:
    data = load_state()
    if not data:
        log.info("No memory file found — starting fresh.")
        return
    trader.import_state(data)
    log.info(
        f"Restored from memory: {len(trader.trade_history)} past trade(s), "
        f"{len(trader.open_positions)} open position(s)."
    )


def performance_by_tag(trade_history: list[dict]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    for t in trade_history:
        if t.get("exit") is None:
            continue
        reason  = (t.get("reasoning") or "")
        pnl     = t.get("pnl", 0)
        matched = [tag for tag in TAGS if tag.lower() in reason.lower()]
        if not matched:
            matched = ["other"]
        for tag in matched:
            r = results.setdefault(tag, {"trades": 0, "wins": 0, "pnl": 0.0})
            r["trades"] += 1
            r["pnl"]    += pnl
            if pnl >= 0:
                r["wins"] += 1
    return results


def build_prompt_context(trade_history: list[dict], lookback: int = 30, max_tags: int = 5) -> str:
    """
    Richer context block for the AI:
    - Overall stats (lookback window)
    - Top performing and worst performing signal patterns
    - Last 5 trade outcomes (streak awareness)
    """
    closed = [t for t in trade_history if t.get("exit") is not None]
    if len(closed) < 3:
        return ""

    recent = closed[-lookback:]
    perf   = performance_by_tag(recent)

    total      = len(recent)
    wins       = sum(1 for t in recent if t.get("pnl", 0) >= 0)
    overall_wr = round(wins / total * 100) if total else 0
    total_pnl  = sum(t.get("pnl", 0) for t in recent)

    # Best & worst patterns
    hot  = sorted([(k, v) for k, v in perf.items() if v["trades"] >= 2],
                  key=lambda x: x[1]["wins"] / x[1]["trades"], reverse=True)
    cold = sorted([(k, v) for k, v in perf.items() if v["trades"] >= 2],
                  key=lambda x: x[1]["wins"] / x[1]["trades"])

    rows = []
    for tag, r in hot[:3]:
        wr = round(r["wins"] / r["trades"] * 100)
        rows.append(f"  🟢 '{tag}': {r['trades']} trades, {wr}% win rate, {r['pnl']:+.4f} USDT")
    for tag, r in cold[:2]:
        wr = round(r["wins"] / r["trades"] * 100)
        if wr < 50:
            rows.append(f"  🔴 '{tag}': {r['trades']} trades, {wr}% win rate, {r['pnl']:+.4f} USDT (AVOID)")

    # Last 5 trade outcomes
    last5 = recent[-5:]
    streak = " ".join("✅" if t.get("pnl", 0) >= 0 else "❌" for t in last5)

    if not rows:
        return ""

    return (
        f"--- PAST PERFORMANCE (last {total} closed trades, "
        f"{overall_wr}% win rate, {total_pnl:+.4f} USDT) ---\n"
        + "\n".join(rows)
        + f"\nLast 5 trades: {streak}"
        + "\nFavor setups marked 🟢. Be extra cautious on setups marked 🔴. "
          "Market conditions change — this is context, not instruction."
    )


def build_learn_report(trade_history: list[dict], lookback: int = 50) -> str:
    closed = [t for t in trade_history if t.get("exit") is not None]
    if not closed:
        return "No closed trades yet — nothing to learn from."
    recent     = closed[-lookback:]
    perf       = performance_by_tag(recent)
    total      = len(recent)
    wins       = sum(1 for t in recent if t.get("pnl", 0) >= 0)
    overall_wr = round(wins / total * 100) if total else 0
    total_pnl  = sum(t.get("pnl", 0) for t in recent)

    lines = [
        f"**Closed trades analysed:** {total}",
        f"**Overall win rate:** {overall_wr}%",
        f"**Total realised P&L:** {total_pnl:+.4f} USDT",
        "",
        "**By reasoning pattern:**",
    ]
    for tag, r in sorted(perf.items(), key=lambda kv: -kv[1]["trades"]):
        wr = round(r["wins"] / r["trades"] * 100) if r["trades"] else 0
        icon = "🟢" if wr >= 55 else ("🔴" if wr < 40 else "🟡")
        lines.append(f"{icon} `{tag}` — {r['trades']} trades, {wr}% win rate, {r['pnl']:+.4f} USDT")

    return "\n".join(lines)
