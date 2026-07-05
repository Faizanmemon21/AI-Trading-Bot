"""
Trader — Binance Testnet order execution
Fixes: correct lot sizes, proper HMAC signing, paper fallback
"""

import logging
import json
import os
import math
import hmac
import hashlib
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import numpy as np
import requests
import CONFIG

log = logging.getLogger("trader")

# Binance testnet URLs
BASE_URL   = "https://testnet.binance.vision/api"
STREAM_URL = "wss://testnet.binance.vision/ws"

# Minimum order sizes per symbol (USDT notional)
MIN_NOTIONAL = {
    "BTCUSDT":  5.0,
    "ETHUSDT":  5.0,
    "SOLUSDT":  5.0,
    "BNBUSDT":  5.0,
    "LINKUSDT": 5.0,
    "AVAXUSDT": 5.0,
    "LTCUSDT":  5.0,
    "UNIUSDT":  5.0,
    "XRPUSDT":  5.0,
    "ADAUSDT":  5.0,
    "DOGEUSDT": 5.0,
    "AAVEUSDT": 5.0,
}

# Quantity precision per symbol (decimal places)
QTY_PRECISION = {
    "BTCUSDT":  5,
    "ETHUSDT":  4,
    "SOLUSDT":  2,
    "BNBUSDT":  3,
    "LINKUSDT": 2,
    "AVAXUSDT": 2,
    "LTCUSDT":  3,
    "UNIUSDT":  2,
    "XRPUSDT":  1,
    "ADAUSDT":  0,
    "DOGEUSDT": 0,
    "AAVEUSDT": 3,
}


class Trader:
    def __init__(self, api_key: str, api_secret: str, budget: float = 100.0):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.budget     = budget

        self.open_positions  = {}
        self.trade_history   = []
        self.daily_pnl       = 0.0
        self.daily_start     = self._utc_midnight()
        self.trading_halted  = False
        self.halt_reason     = ""
        self.halted_at       = None
        self.halted_until    = None      # Stage 10: timed cool-off (loss streak)
        self.consecutive_losses = 0      # Stage 10: circuit-breaker counter
        self.blacklisted_coins = {}

        has_keys = bool(api_key and api_secret)
        lev_state = f"{CONFIG.LEVERAGE_MULTIPLIER}x (SIMULATED — spot testnet has no real margin)" if CONFIG.USE_LEVERAGE else f"{CONFIG.LEVERAGE_MULTIPLIER}x (DISABLED)"
        log.info(
            f"✅ Trader initialized | Budget: ${budget:.2f} | "
            f"Leverage: {lev_state} | "
            f"API keys: {'SET' if has_keys else 'MISSING — paper mode'}"
        )

    # ─────────────────────────────────────────────────────────────────
    # DAILY LOSS GUARD
    # ─────────────────────────────────────────────────────────────────

    def check_daily_loss(self) -> bool:
        """
        Stage 10: guards re-enabled, config-driven.

        1. Resets daily P&L at UTC midnight (and lifts any daily halt).
        2. Lifts an expired loss-streak cool-off (halted_until in the past).
        3. If ENABLE_DAILY_LOSS_GUARD and today's P&L <= -MAX_DAILY_LOSS_PCT%
           of budget -> halt until next UTC midnight.

        Set ENABLE_DAILY_LOSS_GUARD = False in CONFIG.py to restore the old
        "never halt" behaviour.
        """
        now = datetime.now(timezone.utc)

        # New UTC day -> reset daily counters, lift any daily halt
        if now >= self.daily_start + timedelta(days=1):
            self.daily_pnl   = 0.0
            self.daily_start = self._utc_midnight()
            if self.halt_reason.startswith("Daily"):
                self.trading_halted = False
                self.halt_reason    = ""
                self.halted_at      = None

        # Timed cool-off (loss-streak breaker) expired?
        if self.trading_halted and self.halted_until and now >= self.halted_until:
            self.trading_halted     = False
            self.halt_reason        = ""
            self.halted_at          = None
            self.halted_until       = None
            self.consecutive_losses = 0
            log.info("✅ Cool-off finished — trading resumed")

        if self.trading_halted:
            return False

        if not getattr(CONFIG, "ENABLE_DAILY_LOSS_GUARD", True):
            return True

        max_loss = self.budget * getattr(CONFIG, "MAX_DAILY_LOSS_PCT", 5.0) / 100.0
        if self.daily_pnl <= -max_loss:
            self.trading_halted = True
            self.halted_at      = now
            self.halt_reason    = (
                f"Daily loss limit hit ({self.daily_pnl:+.2f} USDT <= -{max_loss:.2f}) "
                f"— halted until next UTC midnight"
            )
            log.warning(f"🛑 {self.halt_reason}")
            return False

        return True

    # ─────────────────────────────────────────────────────────────────
    # POSITION SIZING
    # ─────────────────────────────────────────────────────────────────

    def calculate_position_size(self, symbol: str, price: float) -> float:
        """
        Fixed % sizing scaled to budget, with optional simulated leverage.

        margin_used   = the actual budget % put at risk (unaffected by leverage)
        notional_size = margin_used * LEVERAGE_MULTIPLIER (the actual qty traded)

        NOTE: this bot trades Binance SPOT testnet, which has no real margin
        or liquidation engine. Leverage here is *simulated* — it scales the
        position size (and therefore PnL swings) up, but there is no real
        margin call. SL/TP are still price-percentage based, so at high
        leverage a small price move produces a much larger $ swing relative
        to margin_used. Size accordingly.
        """
        if price <= 0:
            return 0.0

        # Stage 10: per-symbol tiering — this was described in CONFIG's header
        # ("SOL 5%, LTC 0.5%") but never actually implemented. Now it is:
        # PRIMARY_SYMBOLS get BASE_POSITION_PCT, everything else gets the
        # small LEVERAGED_POSITION_PCT probe size.
        primary = [s.strip() for s in getattr(CONFIG, "PRIMARY_SYMBOLS", "").split(",") if s.strip()]
        if primary and symbol not in primary:
            pct = CONFIG.LEVERAGED_POSITION_PCT / 100.0   # e.g. 0.5% = $0.50 margin on $100
        else:
            pct = CONFIG.BASE_POSITION_PCT / 100.0        # e.g. 5.0% = $5.00 margin on $100

        margin_used = self.budget * pct            # $5 on $100 — capital actually "at risk"

        # Never risk more than 10% of budget as margin per trade
        margin_used = min(margin_used, self.budget * 0.10)

        leverage = CONFIG.LEVERAGE_MULTIPLIER if getattr(CONFIG, "USE_LEVERAGE", False) else 1
        usdt_to_spend = margin_used * leverage      # notional size actually traded

        # Enforce Binance minimum notional ($5 minimum)
        min_n = 5.0
        usdt_to_spend = max(usdt_to_spend, min_n)

        raw_qty   = usdt_to_spend / price
        precision = QTY_PRECISION.get(symbol, 4)
        quantity  = math.floor(raw_qty * 10**precision) / 10**precision

        log.info(
            f"  Position size {symbol}: margin=${margin_used:.2f} x{leverage} "
            f"→ notional=${usdt_to_spend:.2f} → {quantity} @ ${price:.4f}"
        )
        return quantity

    # ─────────────────────────────────────────────────────────────────
    # ORDER PLACEMENT
    # ─────────────────────────────────────────────────────────────────

    def place_order(self, symbol: str, side: str, quantity: float,
                    decision: dict) -> dict:
        if self.trading_halted:
            log.warning(f"⛔ Halted: {self.halt_reason}")
            return {"status": "halted"}

        if not self.check_daily_loss():
            return {"status": "daily_limit_hit"}

        if quantity <= 0:
            log.warning(f"  {symbol}: invalid qty={quantity}")
            return {"status": "invalid_quantity"}

        sl_pct = decision.get("stop_loss_pct",   CONFIG.STOP_LOSS_PCT)
        tp_pct = decision.get("take_profit_pct", CONFIG.TAKE_PROFIT_PCT)

        # Try real Binance testnet order first
        if self.api_key and self.api_secret:
            order  = self._binance_market_order(symbol, side, quantity)
            source = "binance_testnet"
        else:
            order  = None
            source = "paper"

        # Fall back to paper trade if Binance fails
        if not order:
            order  = self._paper_order(symbol, side, quantity)
            source = "paper"

        fill_price = self._extract_fill_price(order, symbol)

        if side == "BUY":
            sl_price = fill_price * (1 - sl_pct / 100)
            tp_price = fill_price * (1 + tp_pct / 100)
        else:
            sl_price = fill_price * (1 + sl_pct / 100)
            tp_price = fill_price * (1 - tp_pct / 100)

        # ── Stage 11: leverage-aware bookkeeping + simulated liquidation ──
        # Spot testnet has no real margin engine, so we model one honestly:
        # margin = notional / leverage, and a liquidation price at
        # (100/leverage - maintenance_margin)% adverse move. Without this,
        # high-leverage paper results are fantasy numbers a real futures
        # account could never reproduce.
        leverage    = CONFIG.LEVERAGE_MULTIPLIER if getattr(CONFIG, "USE_LEVERAGE", False) else 1
        notional    = fill_price * quantity
        margin_used = notional / leverage if leverage else notional
        liq_price   = None
        if leverage > 1 and getattr(CONFIG, "SIMULATE_LIQUIDATION", True):
            mm       = getattr(CONFIG, "SIM_MAINT_MARGIN_PCT", 0.5)
            liq_move = max(0.05, 100.0 / leverage - mm)          # % adverse move
            liq_price = (fill_price * (1 - liq_move / 100) if side == "BUY"
                         else fill_price * (1 + liq_move / 100))
            if liq_move < sl_pct:
                log.warning(
                    f"  ⚠️  {symbol}: at {leverage}x, liquidation fires at "
                    f"{liq_move:.2f}% — BEFORE your {sl_pct}% stop loss. "
                    f"Every losing trade on this position = full margin "
                    f"(${margin_used:.2f}) gone."
                )

        position = {
            "symbol":          symbol,
            "side":            side,
            "entry":           fill_price,
            "quantity":        quantity,
            "order_id":        order.get("orderId", f"PAPER-{int(time.time())}"),
            "opened_at":       datetime.now(timezone.utc).timestamp(),
            "stop_loss_pct":   sl_pct,
            "take_profit_pct": tp_pct,
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "reasoning":       decision.get("reasoning", ""),
            "strategy":        decision.get("strategy", ""),
            "leverage":        leverage,
            "margin_used":     round(margin_used, 4),
            "liq_price":       liq_price,
            "source":          source,
        }
        self.open_positions[symbol] = position

        log.info(
            f"  ✅ {source.upper()} {side} {symbol} | "
            f"qty={quantity} @ ${fill_price:.4f} | "
            f"SL=${sl_price:.4f} TP=${tp_price:.4f}"
        )
        return {"status": "success", "order": order,
                "position": position, "fill_price": fill_price}

    # ─────────────────────────────────────────────────────────────────
    # EXIT CHECKING
    # ─────────────────────────────────────────────────────────────────

    def check_exits(self) -> list:
        closed = []
        to_remove = []

        for symbol, pos in list(self.open_positions.items()):
            price = self.get_price(symbol)
            if not price:
                continue

            sl   = pos["stop_loss_price"]
            tp   = pos["take_profit_price"]
            side = pos["side"]

            # Stage 10 telemetry: track how far each trade ran for/against us.
            # (highest_price existed in old trade records but was never updated
            # in this version — restoring it enables MFE/MAE analysis later.)
            pos["highest_price"] = max(pos.get("highest_price") or price, price)
            pos["lowest_price"]  = min(pos.get("lowest_price")  or price, price)

            # ── Stage 11: breakeven/trailing lock ──
            # MFE data showed winners being given back (e.g. UNI +2.4% → SL).
            # Once a trade is up TRAIL_ACTIVATE_PCT, move the stop to
            # entry + TRAIL_LOCK_PCT so it can no longer turn into a loser.
            trail_act = getattr(CONFIG, "TRAIL_ACTIVATE_PCT", 0) or 0
            if trail_act:
                lock  = getattr(CONFIG, "TRAIL_LOCK_PCT", 0.3)
                entry = pos["entry"]
                if side == "BUY":
                    mfe = (pos["highest_price"] - entry) / entry * 100
                    new_sl = entry * (1 + lock / 100)
                    if mfe >= trail_act and new_sl > pos["stop_loss_price"]:
                        pos["stop_loss_price"] = new_sl
                        sl = new_sl
                        log.info(f"  🔒 {symbol} up {mfe:.1f}% — stop moved to breakeven+{lock}%")
                else:
                    mfe = (entry - pos["lowest_price"]) / entry * 100
                    new_sl = entry * (1 - lock / 100)
                    if mfe >= trail_act and new_sl < pos["stop_loss_price"]:
                        pos["stop_loss_price"] = new_sl
                        sl = new_sl
                        log.info(f"  🔒 {symbol} up {mfe:.1f}% — stop moved to breakeven+{lock}%")

            # ── Stage 11: simulated liquidation (checked BEFORE SL/TP,
            #    because on a real futures account it fires first) ──
            liq     = pos.get("liq_price")
            hit_liq = bool(liq) and (price <= liq if side == "BUY" else price >= liq)

            hit_sl = price <= sl if side == "BUY" else price >= sl
            hit_tp = price >= tp if side == "BUY" else price <= tp

            if hit_liq:
                log.warning(f"  💀 {symbol} LIQUIDATED @ ${price:.4f} "
                            f"(liq price ${liq:.4f}, {pos.get('leverage',1)}x)")
                closed.append(self._close_position(symbol, price, "liquidated"))
                to_remove.append(symbol)
            elif hit_sl:
                log.warning(f"  🔴 {symbol} STOP LOSS @ ${price:.4f}")
                closed.append(self._close_position(symbol, price, "stop_loss"))
                to_remove.append(symbol)
            elif hit_tp:
                log.info(f"  🟢 {symbol} TAKE PROFIT @ ${price:.4f}")
                closed.append(self._close_position(symbol, price, "take_profit"))
                to_remove.append(symbol)

        for s in to_remove:
            self.open_positions.pop(s, None)

        return closed

    # ─────────────────────────────────────────────────────────────────
    # BLACKLIST
    # ─────────────────────────────────────────────────────────────────

    def is_blacklisted(self, symbol: str) -> bool:
        # Blacklisting disabled — always tradeable, regardless of past losses
        return False

    def blacklist_symbol(self, symbol: str, reason: str = ""):
        # No-op — blacklisting disabled per user request
        pass

    # ─────────────────────────────────────────────────────────────────
    # MARKET DATA
    # ─────────────────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> float:
        try:
            r = requests.get(
                f"{BASE_URL}/v3/ticker/price",
                params={"symbol": symbol}, timeout=5
            )
            if r.status_code == 200:
                return float(r.json()["price"])
        except Exception as e:
            log.debug(f"Price fetch error {symbol}: {e}")
        return None

    def get_market_data(self, symbol: str) -> dict:
        try:
            r = requests.get(
                f"{BASE_URL}/v3/klines",
                params={"symbol": symbol, "interval": "15m", "limit": 220},
                timeout=10
            )
            if r.status_code != 200:
                log.warning(f"Klines {symbol}: HTTP {r.status_code}")
                return {}

            candles = [
                {
                    "time":   int(k[0]),
                    "open":   float(k[1]),
                    "high":   float(k[2]),
                    "low":    float(k[3]),
                    "close":  float(k[4]),
                    "volume": float(k[5]),
                }
                for k in r.json()
            ]
            if len(candles) < 60:
                return {}

            indicators = self._compute_indicators(candles)
            return {"candles": candles, "indicators": indicators}

        except Exception as e:
            log.error(f"get_market_data {symbol}: {e}")
            return {}

    # ─────────────────────────────────────────────────────────────────
    # STATE
    # ─────────────────────────────────────────────────────────────────

    def export_state(self) -> dict:
        return {
            "open_positions":    list(self.open_positions.values()),
            "trade_history":     self.trade_history,
            "stats":             self._compute_stats(),
            "daily_pnl":         self.daily_pnl,
            "trading_halted":    self.trading_halted,
            "halt_reason":       self.halt_reason,
            "halted_at":         self.halted_at.isoformat() if self.halted_at else None,
            "halted_until":      self.halted_until.isoformat() if self.halted_until else None,
            "consecutive_losses": self.consecutive_losses,
            "blacklisted_coins": self.blacklisted_coins,
        }

    def import_state(self, data: dict):
        self.open_positions    = {p["symbol"]: p for p in data.get("open_positions", [])}
        self.trade_history     = data.get("trade_history", [])
        self.daily_pnl         = data.get("daily_pnl", 0.0)
        self.trading_halted    = data.get("trading_halted", False)
        self.halt_reason       = data.get("halt_reason", "")

        halted_at_str = data.get("halted_at")
        if halted_at_str:
            try:
                self.halted_at = datetime.fromisoformat(halted_at_str)
            except Exception:
                self.halted_at = None
        else:
            self.halted_at = None

        halted_until_str = data.get("halted_until")
        if halted_until_str:
            try:
                self.halted_until = datetime.fromisoformat(halted_until_str)
            except Exception:
                self.halted_until = None
        else:
            self.halted_until = None

        self.consecutive_losses = int(data.get("consecutive_losses", 0) or 0)

        # Safety net: if we were halted but have no timestamp (e.g. old
        # memory.json from before this fix), assume the halt just started
        # now — it will still resume at the next UTC midnight regardless
        if self.trading_halted and not self.halted_at:
            self.halted_at = datetime.now(timezone.utc)
            log.warning(
                "⚠️  Halt flag found with no timestamp (old memory.json) — "
                "will resume at next UTC midnight"
            )

        # ── Stage 11: if a guard was disabled in CONFIG, a halt that guard
        # created earlier should not keep blocking trades from memory.json ──
        if self.trading_halted:
            daily_off  = not getattr(CONFIG, "ENABLE_DAILY_LOSS_GUARD", True)
            streak_off = not (getattr(CONFIG, "MAX_CONSECUTIVE_LOSSES", 0) or 0)
            if (daily_off and self.halt_reason.startswith("Daily")) or \
               (streak_off and "losses in a row" in self.halt_reason):
                log.info(f"🔓 Guard disabled in CONFIG — clearing stale halt "
                         f"('{self.halt_reason}')")
                self.trading_halted = False
                self.halt_reason    = ""
                self.halted_at      = None
                self.halted_until   = None

        self.blacklisted_coins = data.get("blacklisted_coins", {})
        log.info(
            f"State restored: {len(self.open_positions)} open, "
            f"{len(self.trade_history)} trade history"
            + (f" | HALTED until next UTC midnight"
               if self.trading_halted else "")
        )

    def _compute_stats(self) -> dict:
        closed  = [t for t in self.trade_history if t.get("exit")]
        wins    = [t for t in closed if t["pnl"] >= 0]
        losses  = [t for t in closed if t["pnl"] < 0]
        tw      = sum(t["pnl"] for t in wins)
        tl      = abs(sum(t["pnl"] for t in losses))
        return {
            "total_trades":  len(closed),
            "wins":          len(wins),
            "losses":        len(losses),
            "accuracy_pct":  round(len(wins)/len(closed)*100, 1) if closed else 0,
            "profit_factor": round(tw/tl, 2) if tl > 0 else 0,
            "realized_pnl":  round(tw - tl, 4),
            "avg_win":       round(tw/len(wins), 4) if wins else 0,
            "avg_loss":      round(tl/len(losses), 4) if losses else 0,
            "open_positions": len(self.open_positions),
        }

    # ─────────────────────────────────────────────────────────────────
    # PRIVATE — BINANCE API
    # ─────────────────────────────────────────────────────────────────

    def _binance_market_order(self, symbol: str, side: str,
                               quantity: float) -> dict:
        precision = QTY_PRECISION.get(symbol, 4)
        qty_str   = f"{quantity:.{precision}f}"

        params = {
            "symbol":    symbol,
            "side":      side,
            "type":      "MARKET",
            "quantity":  qty_str,
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        params["signature"] = self._sign(params)

        try:
            r = requests.post(
                f"{BASE_URL}/v3/order",
                params=params,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10,
            )
            if r.status_code == 200:
                log.info(f"  Binance order OK: {r.json().get('orderId')}")
                return r.json()
            else:
                log.warning(f"  Binance order failed ({r.status_code}): {r.text[:200]}")
                return None
        except Exception as e:
            log.warning(f"  Binance order exception: {e}")
            return None

    def _paper_order(self, symbol: str, side: str, quantity: float) -> dict:
        """Simulates an order fill at current market price."""
        price = self.get_price(symbol) or 0.0
        oid   = int(time.time() * 1000)
        log.info(f"  📝 PAPER {side} {symbol} {quantity} @ ${price:.4f}")
        return {
            "orderId":              oid,
            "symbol":               symbol,
            "side":                 side,
            "type":                 "MARKET",
            "executedQty":          str(quantity),
            "cummulativeQuoteQty":  str(quantity * price),
            "price":                str(price),
            "status":               "FILLED",
            "simulated":            True,
        }

    def _extract_fill_price(self, order: dict, symbol: str) -> float:
        try:
            exec_qty = float(order.get("executedQty", 0) or 0)
            quote    = float(order.get("cummulativeQuoteQty", 0) or 0)
            if exec_qty > 0 and quote > 0:
                return quote / exec_qty
            p = order.get("price", "0")
            if p and float(p) > 0:
                return float(p)
        except Exception:
            pass
        return self.get_price(symbol) or 0.0

    def _sign(self, params: dict) -> str:
        if not self.api_secret:
            raise ValueError("BINANCE_API_SECRET not set in .env")
        qs = urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"),
            qs.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _close_position(self, symbol: str, price: float,
                         reason: str) -> dict:
        pos = self.open_positions.get(symbol, {})
        qty = float(pos.get("quantity", 0))
        pnl = (price - pos["entry"]) * qty
        if pos.get("side") == "SELL":
            pnl = -pnl

        # ── Stage 11: honest isolated-margin accounting ──
        # On a real futures account you cannot lose more than the margin
        # posted on the position; a liquidation takes exactly that margin.
        lev    = pos.get("leverage", 1) or 1
        margin = pos.get("margin_used")
        if margin:
            if reason == "liquidated":
                pnl = -float(margin)
            elif lev > 1 and pnl < -float(margin):
                pnl = -float(margin)

        trade = {
            "symbol":      symbol,
            "side":        pos.get("side"),
            "entry":       pos.get("entry"),
            "exit":        price,
            "quantity":    qty,
            "pnl":         round(pnl, 6),
            "exit_reason": reason,
            "reasoning":   pos.get("reasoning", ""),
            "strategy":    pos.get("strategy", ""),
            "leverage":    lev,
            "margin_used": margin,
            "time":        datetime.now(timezone.utc).timestamp(),
            "highest_price": pos.get("highest_price"),
            "lowest_price":  pos.get("lowest_price"),
        }
        self.trade_history.append(trade)
        self.daily_pnl += pnl

        # Stage 10: consecutive-loss circuit breaker.
        # MAX_CONSECUTIVE_LOSSES / CONSECUTIVE_LOSS_HALT_H existed in CONFIG
        # since Stage 9 but were never wired up — now they are.
        if pnl < 0:
            self.consecutive_losses += 1
            max_streak = getattr(CONFIG, "MAX_CONSECUTIVE_LOSSES", 0) or 0
            if max_streak and self.consecutive_losses >= max_streak and not self.trading_halted:
                halt_h = getattr(CONFIG, "CONSECUTIVE_LOSS_HALT_H", 4)
                self.trading_halted = True
                self.halted_at      = datetime.now(timezone.utc)
                self.halted_until   = self.halted_at + timedelta(hours=halt_h)
                self.halt_reason    = (
                    f"{self.consecutive_losses} losses in a row — cooling off {halt_h}h "
                    f"(until {self.halted_until.strftime('%H:%M UTC')})"
                )
                log.warning(f"🛑 {self.halt_reason}")
        else:
            self.consecutive_losses = 0

        # Blacklisting disabled — bot keeps trading every symbol regardless
        # of how many losses it takes on that coin.

        return trade

    # ─────────────────────────────────────────────────────────────────
    # PRIVATE — INDICATORS
    # ─────────────────────────────────────────────────────────────────

    def _compute_indicators(self, candles: list) -> dict:
        if len(candles) < 60:
            return {}
        try:
            c  = np.array([x["close"]  for x in candles], dtype=float)
            h  = np.array([x["high"]   for x in candles], dtype=float)
            lo = np.array([x["low"]    for x in candles], dtype=float)
            v  = np.array([x["volume"] for x in candles], dtype=float)

            ema20  = self._ema(c, 20)
            ema50  = self._ema(c, 50)
            ema200 = self._ema(c, 200) if len(c) >= 200 else ema50

            ema12  = self._ema(c, 12)
            ema26  = self._ema(c, 26)
            macd   = ema12 - ema26

            # Real MACD signal line from history
            macd_arr    = self._ema_array(c, 12) - self._ema_array(c, 26)
            signal_arr  = self._ema_array(macd_arr, 9)
            macd_hist   = macd_arr[-1] - signal_arr[-1]
            macd_hist_p = macd_arr[-2] - signal_arr[-2] if len(macd_arr) > 1 else 0
            macd_signal = signal_arr[-1]

            # RSI
            rsi = self._rsi(c, 14)

            # Bollinger Bands
            sma20   = float(np.mean(c[-20:]))
            std20   = float(np.std(c[-20:]))
            bb_up   = sma20 + 2 * std20
            bb_lo   = sma20 - 2 * std20
            bb_w    = (bb_up - bb_lo) / sma20 * 100 if sma20 else 1
            bb_pos  = ((c[-1] - bb_lo) / (bb_up - bb_lo)) if (bb_up - bb_lo) else 0.5

            # StochRSI
            rsi_arr = self._rsi_array(c, 14)
            stoch_k = self._stoch_k(rsi_arr, 14)

            # OBV
            obv      = self._obv(c, v)
            obv_trend = "rising" if obv[-1] > np.mean(obv[-14:]) else "falling"

            # Volume ratio
            vol_ratio = float(np.mean(v[-5:])) / float(np.mean(v[-20:])) if np.mean(v[-20:]) > 0 else 1.0

            # ATR
            tr    = np.maximum(h[-15:] - lo[-15:],
                    np.maximum(np.abs(h[-15:] - c[-16:-1]),
                               np.abs(lo[-15:] - c[-16:-1])))
            atr   = float(np.mean(tr))
            atr_p = atr / c[-1] * 100 if c[-1] else 1.0

            # Returns
            def ret(n):
                return float((c[-1]/c[-n]-1)*100) if len(c) >= n else 0.0

            return {
                "close":         float(c[-1]),
                "rsi":           float(rsi),
                "ema20":         float(ema20),
                "ema50":         float(ema50),
                "ema200":        float(ema200),
                "macd":          float(macd),
                "macd_signal":   float(macd_signal),
                "macd_hist":     float(macd_hist),
                "macd_hist_prev": float(macd_hist_p),
                "bb_upper":      float(bb_up),
                "bb_lower":      float(bb_lo),
                "bb_width":      float(bb_w),
                "bb_pos":        float(bb_pos),
                "stoch_k":       float(stoch_k),
                "obv_trend":     obv_trend,
                "vol_ratio":     float(vol_ratio),
                "atr":           float(atr),
                "atr_pct":       float(atr_p),
                "adx":           float(self._adx(h, lo, c)),   # Stage 10: real ADX (was hardcoded 20.0)
                "ret_1h":        ret(4),
                "ret_4h":        ret(16),
                "ret_12h":       ret(48),
                "ret_24h":       ret(96),
                "body_size":     abs(float(c[-1] - c[-2])),
                "upper_wick":    float(h[-1]) - max(float(c[-1]), float(c[-2])),
                "lower_wick":    min(float(c[-1]), float(c[-2])) - float(lo[-1]),
                "bullish_candle": bool(c[-1] > c[-2]),
            }
        except Exception as e:
            log.error(f"Indicator error: {e}")
            return {}

    # ── math helpers ──────────────────────────────────────────────────

    def _ema(self, data: np.ndarray, p: int) -> float:
        return float(self._ema_array(data, p)[-1])

    def _ema_array(self, data: np.ndarray, p: int) -> np.ndarray:
        k   = 2 / (p + 1)
        out = np.zeros(len(data))
        out[0] = data[0]
        for i in range(1, len(data)):
            out[i] = data[i] * k + out[i-1] * (1-k)
        return out

    def _rsi(self, c: np.ndarray, p: int = 14) -> float:
        return float(self._rsi_array(c, p)[-1])

    def _rsi_array(self, c: np.ndarray, p: int = 14) -> np.ndarray:
        d    = np.diff(c)
        gain = np.where(d > 0, d, 0.0)
        loss = np.where(d < 0, -d, 0.0)
        out  = np.full(len(c), 50.0)
        for i in range(p, len(d)):
            ag = np.mean(gain[i-p:i])
            al = np.mean(loss[i-p:i])
            out[i+1] = 100 - 100/(1 + ag/al) if al else 100.0
        return out

    def _stoch_k(self, rsi_arr: np.ndarray, p: int = 14) -> float:
        if len(rsi_arr) < p:
            return 50.0
        window = rsi_arr[-p:]
        lo, hi = window.min(), window.max()
        if hi == lo:
            return 50.0
        return float((rsi_arr[-1] - lo) / (hi - lo) * 100)

    def _adx(self, h: np.ndarray, lo: np.ndarray, c: np.ndarray, p: int = 14) -> float:
        """
        Wilder ADX(14). Stage 10: replaces the old hardcoded 20.0 so the ML
        model's 'adx' and 'trending' features finally receive real values.
        Falls back to 20.0 (neutral) on short data or any numeric error.
        """
        n = len(c)
        if n < p * 2 + 2:
            return 20.0
        try:
            up_move   = h[1:] - h[:-1]
            down_move = lo[:-1] - lo[1:]
            plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
            tr = np.maximum(
                h[1:] - lo[1:],
                np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1]))
            )

            alpha = 1.0 / p

            def _wilder(x: np.ndarray) -> np.ndarray:
                out = np.empty(len(x))
                out[0] = x[0]
                for i in range(1, len(x)):
                    out[i] = out[i - 1] + alpha * (x[i] - out[i - 1])
                return out

            atr_s = _wilder(tr)
            pdm_s = _wilder(plus_dm)
            mdm_s = _wilder(minus_dm)

            with np.errstate(divide="ignore", invalid="ignore"):
                pdi  = np.where(atr_s > 0, 100.0 * pdm_s / atr_s, 0.0)
                mdi  = np.where(atr_s > 0, 100.0 * mdm_s / atr_s, 0.0)
                dsum = pdi + mdi
                dx   = np.where(dsum > 0, 100.0 * np.abs(pdi - mdi) / dsum, 0.0)

            adx_series = _wilder(dx[p:])   # skip warm-up bars
            val = float(adx_series[-1])
            return val if np.isfinite(val) else 20.0
        except Exception:
            return 20.0

    def _obv(self, c: np.ndarray, v: np.ndarray) -> np.ndarray:
        obv = np.zeros(len(c))
        obv[0] = v[0]
        for i in range(1, len(c)):
            obv[i] = obv[i-1] + (v[i] if c[i] > c[i-1] else (-v[i] if c[i] < c[i-1] else 0))
        return obv

    def _kelly_pct(self, symbol: str) -> float:
        trades = [t for t in self.trade_history if t["symbol"] == symbol and t.get("exit")]
        if len(trades) < 5:
            return 0.02
        wins   = [t for t in trades if t["pnl"] >= 0]
        losses = [t for t in trades if t["pnl"] < 0]
        if not wins or not losses:
            return 0.02
        wr  = len(wins) / len(trades)
        aw  = sum(t["pnl"] for t in wins) / len(wins)
        al  = abs(sum(t["pnl"] for t in losses) / len(losses))
        k   = (wr * aw - (1-wr) * al) / aw if aw else 0
        return max(0, min(k, 0.25))

    def _utc_midnight(self) -> datetime:
        n = datetime.now(timezone.utc)
        return n.replace(hour=0, minute=0, second=0, microsecond=0)
