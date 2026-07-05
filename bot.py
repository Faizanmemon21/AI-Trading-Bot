"""
Bot — Main trading loop (Discord DISABLED)
All output goes to console only.
"""

import warnings
warnings.filterwarnings("ignore")

import asyncio
import logging
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

from trader import Trader
from analyst import Analyst
from memory import load_into_trader, save_state, build_learn_report
import CONFIG

# ─────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, CONFIG.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("bot")

# ─────────────────────────────────────────────────────────────────────
# CONFIG FROM .env
# ─────────────────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY")

# ─────────────────────────────────────────────────────────────────────
# ANTHROPIC CLIENT (optional)
# ─────────────────────────────────────────────────────────────────────
client = None
try:
    if ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY) > 10:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        log.info("✅ Anthropic client ready — Claude analysis enabled")
    else:
        log.info("ℹ️  No ANTHROPIC_API_KEY — indicator-only mode")
except Exception as e:
    log.warning(f"Anthropic init failed ({e}) — indicator-only mode")

# ─────────────────────────────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────────────────────────────
trader      = None
analyst     = None
cycle_count = 0

# ─────────────────────────────────────────────────────────────────────
# CONSOLE REPORTER
# ─────────────────────────────────────────────────────────────────────
def print_startup(symbols, interval, budget):
    print("\n" + "=" * 60)
    print("  🤖  CryptoBot — Trading Engine (console mode)")
    print("=" * 60)
    print(f"  Symbols  : {', '.join(symbols)}")
    print(f"  Interval : every {interval} minutes")
    print(f"  Budget   : ${budget:.2f} USDT (Testnet)")
    print(f"  Session  : {CONFIG.TRADING_SESSION_START:02d}:00 – {CONFIG.TRADING_SESSION_END:02d}:00 UTC")
    print(f"  SL / TP  : {CONFIG.STOP_LOSS_PCT}% / {CONFIG.TAKE_PROFIT_PCT}%")
    print(f"  Discord  : DISABLED")
    print("=" * 60 + "\n")

def print_stats(stats):
    pnl  = stats.get("realized_pnl", 0)
    icon = "📈" if pnl >= 0 else "📉"
    print(
        f"{icon} Stats | trades={stats.get('total_trades',0)} "
        f"W={stats.get('wins',0)} L={stats.get('losses',0)} "
        f"acc={stats.get('accuracy_pct',0)}% "
        f"P&L={pnl:+.4f} USDT"
    )

# ─────────────────────────────────────────────────────────────────────
# MAIN TRADING CYCLE
# ─────────────────────────────────────────────────────────────────────
async def trading_cycle():
    global cycle_count
    cycle_count += 1

    now  = datetime.now(timezone.utc)
    hour = now.hour

    print(f"\n{'═'*20} CYCLE {cycle_count} — {now.strftime('%H:%M UTC')} {'═'*20}")

    # Session check
    if not (CONFIG.TRADING_SESSION_START <= hour < CONFIG.TRADING_SESSION_END):
        log.info(f"Outside session ({CONFIG.TRADING_SESSION_START:02d}:00–{CONFIG.TRADING_SESSION_END:02d}:00 UTC) — waiting")
        return

    # Daily loss guard
    if not trader.check_daily_loss():
        print(f"🛑 {trader.halt_reason}")
        return

    # Check exits on open positions
    closed = trader.check_exits()
    for c in closed:
        if c:
            pnl_sign = "+" if c["pnl"] >= 0 else ""
            icon = "✅" if c["pnl"] >= 0 else "❌"
            print(
                f"  {icon} CLOSED {c['symbol']} @ ${c['exit']:.4f} | "
                f"P&L: {pnl_sign}{c['pnl']:.4f} USDT ({c.get('exit_reason','')})"
            )

    # Analyse each symbol
    symbols = CONFIG.SYMBOLS.split(",")
    buys = 0
    decisions = {}
    market_prices = {}

    for symbol in symbols:
        try:
            market_data = trader.get_market_data(symbol)
            if not market_data or not market_data.get("indicators"):
                log.warning(f"  {symbol}: no market data")
                continue

            ind   = market_data["indicators"]
            price = ind.get("close", 0)

            decision   = analyst.analyze(symbol, market_data)
            decisions[symbol] = decision
            market_prices[symbol] = price
            action     = decision.get("action", "HOLD")
            confidence = decision.get("confidence", 0)
            reasoning  = decision.get("reasoning", "")

            icon = "🟢" if action == "BUY" else ("🔴" if action == "SELL" else "⚪")
            print(
                f"  {icon} {action:4s} {symbol:10s} @ ${price:10.4f} | "
                f"conf={confidence:3d} | {reasoning[:55]}"
            )

            # Place order — enforce max open positions
            max_pos = getattr(CONFIG, "MAX_OPEN_POSITIONS", 2)
            already_open = symbol in trader.open_positions

            min_conf = getattr(CONFIG, "MIN_CONFIDENCE_TO_TRADE", 20)
            if action in ("BUY", "SELL") and confidence >= min_conf:
                if already_open:
                    print(f"    ⏭️  {symbol} already open — skipping")
                elif len(trader.open_positions) >= max_pos:
                    print(f"    ⏭️  Max positions ({max_pos}) reached — skipping {symbol}")
                else:
                    qty    = trader.calculate_position_size(symbol, price)
                    result = trader.place_order(symbol, action, qty, decision)

                    if result.get("status") == "success":
                        fill = result.get("fill_price", price)
                        print(f"    ✅ ORDER PLACED: {action} {qty:.6f} {symbol} @ ${fill:.4f}")
                        buys += 1
                    else:
                        print(f"    ⚠️  Order failed: {result.get('status')} — {result.get('error','')}")

        except Exception as e:
            log.error(f"  {symbol}: {e}")

    # Summary
    stats = trader._compute_stats()
    print(
        f"\n  Summary | open={len(trader.open_positions)} "
        f"daily_pnl={trader.daily_pnl:+.4f} | "
        f"total={stats.get('total_trades',0)} trades "
        f"acc={stats.get('accuracy_pct',0)}% "
        f"pnl={stats.get('realized_pnl',0):+.4f}"
    )

    # Save full state for dashboard
    try:
        import json, time
        stats = trader._compute_stats()
        # Build signals list from latest decisions
        signal_list = []
        for sym, dec in decisions.items():
            signal_list.append({
                "symbol":    sym,
                "action":    dec.get("action", "HOLD"),
                "confidence": dec.get("confidence", 0),
                "reasoning": dec.get("reasoning", ""),
                "entry":     market_prices.get(sym, 0),
                "time":      time.time(),
                # Stage 11: real attribution instead of hardcoded "RSI+BB"
                "strategy":  dec.get("strategy", "unknown"),
                "regime":    dec.get("regime", "?"),
                "bulls_entering": dec.get("bulls_entering", False),
                "bears_entering": dec.get("bears_entering", False),
            })

        bot_state_data = {
            "stats": {
                **stats,
                "open_longs":  sum(1 for p in trader.open_positions.values() if p.get("side") == "BUY"),
                "open_shorts": sum(1 for p in trader.open_positions.values() if p.get("side") == "SELL"),
                "profit_factor": stats.get("profit_factor", 0),
                "avg_win":     stats.get("avg_win", 0),
                "avg_loss":    stats.get("avg_loss", 0),
                "coin_stats":  {},
            },
            "positions":      list(trader.open_positions.values()),
            "trade_history":  trader.trade_history,
            "signals":        signal_list,
            "prices":         market_prices,
            "timestamp":      time.time(),
            "bot_online":     True,
            "blacklisted_coins": trader.blacklisted_coins,
            "daily_pnl":      trader.daily_pnl,
            "trading_halted": trader.trading_halted,
            "halt_reason":    trader.halt_reason,
        }
        with open("bot_state.json", "w") as f:
            json.dump(bot_state_data, f, default=str)
    except Exception as e:
        log.error(f"State save error: {e}")
    save_state(trader)

# ─────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────
async def run_bot():
    global trader, analyst

    log.info("🚀 Starting CryptoBot...")

    budget = CONFIG.TESTNET_BUDGET if CONFIG.USE_TESTNET else CONFIG.LIVE_BUDGET
    trader = Trader(BINANCE_API_KEY, BINANCE_API_SECRET, budget=budget)
    load_into_trader(trader)

    analyst = Analyst(client, trader)

    symbols = CONFIG.SYMBOLS.split(",")
    print_startup(symbols, CONFIG.INTERVAL_MINS, budget)

    try:
        while True:
            await trading_cycle()
            await asyncio.sleep(CONFIG.INTERVAL_MINS * 60)
    except KeyboardInterrupt:
        print("\n⏹️  Bot stopped by user")
        save_state(trader)
        print_stats(trader._compute_stats())

if __name__ == "__main__":
    asyncio.run(run_bot())
