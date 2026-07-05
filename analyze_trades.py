#!/usr/bin/env python3
"""
analyze_trades.py — Strategy attribution + leverage what-if for CryptoBot.

Reads memory.json (or bot_state.json) and answers:
  1. Which signal combo is actually making money (attribution)
  2. Performance by symbol, exit reason, entry-RSI depth
  3. MFE/MAE: how far trades ran for/against us (trailing-stop case)
  4. Loss-streak statistics (is "2 in a row" normal for this win rate?)
  5. What-if: replay history at any leverage WITH liquidation modelling

Usage:
    python analyze_trades.py memory.json
    python analyze_trades.py memory.json --leverage 75
"""

import json
import re
import sys
import math
import argparse
from collections import defaultdict


# ──────────────────────────────────────────────────────────────────────
def load_trades(path):
    with open(path) as f:
        data = json.load(f)
    trades = [t for t in data.get("trade_history", []) if t.get("exit")]
    return data, trades


def pf(wins_sum, loss_sum):
    return round(wins_sum / loss_sum, 2) if loss_sum > 0 else float("inf")


def summarize(trades):
    wins   = [t for t in trades if t["pnl"] >= 0]
    losses = [t for t in trades if t["pnl"] < 0]
    tw = sum(t["pnl"] for t in wins)
    tl = abs(sum(t["pnl"] for t in losses))
    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "pnl": round(tw - tl, 2),
        "pf": pf(tw, tl),
        "avg_win": round(tw / len(wins), 2) if wins else 0,
        "avg_loss": round(tl / len(losses), 2) if losses else 0,
    }


def fmt(label, s, width=26):
    return (f"  {label:<{width}} n={s['n']:>3}  WR={s['wr']:>5.1f}%  "
            f"PnL={s['pnl']:>+8.2f}  PF={s['pf']:>5}  "
            f"avgW={s['avg_win']:>5.2f} avgL={s['avg_loss']:>5.2f}")


# ──────────────────────────────────────────────────────────────────────
def signal_tag(reasoning):
    """Collapse a reasoning string into an attributable signal combo."""
    r = reasoning or ""
    tags = []
    if "COMBO" in r:
        tags.append("COMBO")
    if "StochRSI" in r:
        tags.append("StochRSI")
    if re.search(r"\bRSI\(", r):
        tags.append("RSI")
    if "MACD" in r:
        tags.append("MACD")
    if "EMA" in r or "Uptrend" in r:
        tags.append("TREND")
    if "news" in r.lower():
        tags.append("NEWS")
    if not tags:
        return "OTHER/" + (r[:20] or "blank")
    return "+".join(sorted(set(tags)))


def entry_rsi(reasoning):
    m = re.search(r"RSI\((\d+)\)", reasoning or "")
    return int(m.group(1)) if m else None


def mae_pct(t):
    """Max adverse excursion % (how far price went AGAINST entry)."""
    e = t.get("entry")
    if not e:
        return None
    if t.get("side") == "BUY":
        lo = t.get("lowest_price")
        return (e - lo) / e * 100 if lo else None
    hi = t.get("highest_price")
    return (hi - e) / e * 100 if hi else None


def mfe_pct(t):
    """Max favourable excursion % (how far price went FOR entry)."""
    e = t.get("entry")
    if not e:
        return None
    if t.get("side") == "BUY":
        hi = t.get("highest_price")
        return (hi - e) / e * 100 if hi else None
    lo = t.get("lowest_price")
    return (e - lo) / e * 100 if lo else None


def max_loss_streak(trades):
    best = cur = 0
    for t in trades:
        if t["pnl"] < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# ──────────────────────────────────────────────────────────────────────
def leverage_whatif(trades, leverage, maint_margin_pct=0.5, taker_fee_pct=0.05):
    """
    Replay closed trades at a given leverage with a liquidation model.

    Assumes margin per trade = notional / leverage stays the SAME dollar
    amount as the original trade's margin, so results are comparable in
    'margin dollars'. A long is liquidated when the adverse move exceeds
    (100/leverage - maint_margin_pct)%.  Losses are capped at -100% of
    margin (that is what liquidation means).

    Uses recorded highest/lowest price, which is sampled once per bot
    cycle — the TRUE intracycle extreme is worse, so liquidations here
    are a LOWER BOUND on reality.
    """
    liq_move = 100.0 / leverage - maint_margin_pct  # % adverse move to liquidate
    results = []
    skipped = 0

    for t in trades:
        entry, exit_p = t.get("entry"), t.get("exit")
        if not entry or not exit_p:
            skipped += 1
            continue
        mae = mae_pct(t)
        if mae is None:
            skipped += 1
            continue

        move_pct = (exit_p - entry) / entry * 100
        if t.get("side") == "SELL":
            move_pct = -move_pct

        fees = 2 * taker_fee_pct * leverage  # entry+exit taker fees on notional, as % of margin

        if mae >= liq_move:
            ret_on_margin = -100.0
            outcome = "LIQUIDATED"
        else:
            ret_on_margin = move_pct * leverage - fees
            outcome = "win" if ret_on_margin >= 0 else "loss"
        results.append({"t": t, "ret": ret_on_margin, "outcome": outcome,
                        "mae": mae, "orig_win": t["pnl"] >= 0})

    return liq_move, results, skipped


# ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="memory.json")
    ap.add_argument("--leverage", type=float, default=None,
                    help="Replay history at this leverage with liquidation modelling")
    ap.add_argument("--maint-margin", type=float, default=0.5,
                    help="Maintenance margin %% used in liquidation model (default 0.5)")
    ap.add_argument("--last", type=int, default=None,
                    help="Only analyze the most recent N trades")
    args = ap.parse_args()

    data, trades = load_trades(args.path)
    if args.last:
        trades = trades[-args.last:]
    if not trades:
        print("No closed trades found.")
        sys.exit(0)

    print("=" * 78)
    print(f"  TRADE ANALYSIS — {len(trades)} closed trades from {args.path}")
    print("=" * 78)

    # 1. Overall + recent windows
    print("\n## OVERALL")
    print(fmt("all trades", summarize(trades)))
    for n in (29, 10):
        if len(trades) > n:
            print(fmt(f"last {n}", summarize(trades[-n:])))

    # 2. Attribution by signal combo  ← "which strategy is working best"
    print("\n## BY SIGNAL COMBO (parsed from trade reasoning)")
    groups = defaultdict(list)
    for t in trades:
        groups[signal_tag(t.get("reasoning"))].append(t)
    for tag, ts in sorted(groups.items(), key=lambda kv: -summarize(kv[1])["pnl"]):
        print(fmt(tag, summarize(ts)))

    # 3. By exit reason
    print("\n## BY EXIT REASON")
    groups = defaultdict(list)
    for t in trades:
        groups[t.get("exit_reason", "?")].append(t)
    for tag, ts in sorted(groups.items()):
        print(fmt(tag, summarize(ts)))

    # 4. By entry RSI depth (how oversold were we buying?)
    print("\n## BY ENTRY RSI (dip depth)")
    buckets = {"RSI < 20": [], "RSI 20-29": [], "RSI 30-39": [], "RSI >= 40": [], "no RSI logged": []}
    for t in trades:
        r = entry_rsi(t.get("reasoning"))
        if r is None:
            buckets["no RSI logged"].append(t)
        elif r < 20:
            buckets["RSI < 20"].append(t)
        elif r < 30:
            buckets["RSI 20-29"].append(t)
        elif r < 40:
            buckets["RSI 30-39"].append(t)
        else:
            buckets["RSI >= 40"].append(t)
    for tag, ts in buckets.items():
        if ts:
            print(fmt(tag, summarize(ts)))

    # 5. By symbol
    print("\n## BY SYMBOL (sorted by PnL)")
    groups = defaultdict(list)
    for t in trades:
        groups[t.get("symbol", "?")].append(t)
    for tag, ts in sorted(groups.items(), key=lambda kv: -summarize(kv[1])["pnl"]):
        print(fmt(tag, summarize(ts)))

    # 6. MFE on losers — money left on the table
    print("\n## MFE ON LOSING TRADES (how far into profit before dying)")
    losers = [t for t in trades if t["pnl"] < 0]
    mfes = [(t, mfe_pct(t)) for t in losers]
    mfes = [(t, m) for t, m in mfes if m is not None]
    if mfes:
        for thresh in (1.0, 1.5, 2.0, 3.0):
            n = sum(1 for _, m in mfes if m >= thresh)
            print(f"  losers that were up ≥ {thresh:.1f}% first: {n}/{len(mfes)}"
                  f"  ({n/len(mfes)*100:.0f}%)")
        avg = sum(m for _, m in mfes) / len(mfes)
        print(f"  average MFE on losers: {avg:.2f}%   "
              f"(TP is typically 4.0-4.5% away)")
    else:
        print("  no MFE data on losers (old records lack highest/lowest price)")

    # 7. MAE on winners — how deep winners dipped before paying
    print("\n## MAE ON WINNING TRADES (drawdown survived before profit)")
    winners = [t for t in trades if t["pnl"] >= 0]
    maes = [(t, mae_pct(t)) for t in winners]
    maes = [(t, m) for t, m in maes if m is not None]
    if maes:
        for thresh in (0.5, 0.83, 1.0, 1.33):
            n = sum(1 for _, m in maes if m >= thresh)
            print(f"  winners that first dipped ≥ {thresh:.2f}%: {n}/{len(maes)}"
                  f"  ({n/len(maes)*100:.0f}%)")
    else:
        print("  no MAE data on winners")

    # 8. Streaks
    print("\n## LOSS STREAKS")
    s = summarize(trades)
    p_loss = 1 - s["wr"] / 100
    exp_streak = math.log(max(len(trades), 2)) / -math.log(p_loss) if 0 < p_loss < 1 else 0
    print(f"  longest historical loss streak : {max_loss_streak(trades)}")
    print(f"  expected max streak at {s['wr']}% WR over {len(trades)} trades : ~{exp_streak:.0f}")
    print("  → streaks of this size are normal variance for this win rate,")
    print("    not proof the strategy broke.")

    # 9. Leverage what-if
    if args.leverage:
        L = args.leverage
        liq_move, res, skipped = leverage_whatif(trades, L, args.maint_margin)
        print("\n" + "=" * 78)
        print(f"  WHAT-IF REPLAY AT {L:g}x  (liquidation if adverse move ≥ {liq_move:.2f}%)")
        print("=" * 78)
        if skipped:
            print(f"  ({skipped} old trades skipped — no highest/lowest price recorded)")
        liq = [r for r in res if r["outcome"] == "LIQUIDATED"]
        liq_would_have_won = [r for r in liq if r["orig_win"]]
        wins = [r for r in res if r["ret"] >= 0]
        total_ret = sum(r["ret"] for r in res)
        print(f"  trades replayed        : {len(res)}")
        print(f"  liquidated             : {len(liq)}  ({len(liq)/len(res)*100:.0f}%)"
              if res else "")
        print(f"  …of which were WINNERS at current settings: {len(liq_would_have_won)}")
        print(f"  surviving winners      : {len(wins)}")
        print(f"  net return             : {total_ret:+.0f}% of one trade's margin "
              f"(sum across {len(res)} trades)")
        print(f"  average per trade      : {total_ret/len(res):+.1f}% of margin" if res else "")
        print("\n  ⚠ highest/lowest prices are sampled once per bot cycle, so true")
        print("    intracycle wicks are WORSE — real liquidation count would be HIGHER.")

    print()


if __name__ == "__main__":
    main()
