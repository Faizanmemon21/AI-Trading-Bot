"""
strategy_v2.py — Multi-strategy engine with regime detection + news hook.

Built from the actual trade history in memory.json (86 closed trades):

  WHAT THE DATA SAID (as of 2026-07-05):
    RSI+StochRSI double-oversold dips :  87.5% WR, +52.80  ← best signal
    Uptrend-tagged entries            :  60-75% WR, +45    ← second best
    StochRSI-only dips                :  33% WR but +24.78 (big winners)
    MACD-only                         :  28.6% WR, +19.03 (rare, huge wins)
    MACD+TREND                        :  19.0% WR, -1.42   ← biggest leak
    RSI-only (no StochRSI confirm)    :  20.0% WR, -1.99   ← leak
    OBV-only entries                  :   0.0% WR, -16.98  ← worst leak

  DESIGN CONSEQUENCES:
    1. DIP_REVERSAL (RSI *and* StochRSI oversold together) is the flagship
       strategy — this is what has been making the money.
    2. Your original momentum strategy is PRESERVED as TREND_MOMENTUM,
       but its entry bar is raised (the 19% WR combo needs more filters,
       not more trades).
    3. Single-indicator entries (RSI alone, OBV alone) are no longer
       enough to trade — they need a second confirmation.
    4. NEW: short side (SHORT_REVERSAL / SHORT_TREND) so a bearish market
       is a trading opportunity instead of a blocked trade.
    5. NEW: regime detector — BULL / BEAR / CHOP plus a "bulls_entering" /
       "bears_entering" early-flip flag.
    6. NEW: news sentiment hook — pass a score in [-1.0 .. +1.0] and it
       shifts confidence toward/away from the trade.
    7. Every decision carries a "strategy" tag so analyze_trades.py can
       attribute wins/losses per strategy from now on.

Interfaces:
    StrategyEngine.analyze(symbol, market_data, news_sentiment=None) -> decision dict
    AnalystShim(client, trader)  — drop-in replacement for Analyst in bot.py

Decision dict:
    {
      "action": "BUY" | "SELL" | "HOLD",
      "confidence": 0-100,
      "reasoning": str,
      "strategy": "DIP_REVERSAL" | "TREND_MOMENTUM" | "SHORT_REVERSAL"
                  | "SHORT_TREND" | "NONE",
      "regime": "BULL" | "BEAR" | "CHOP",
      "bulls_entering": bool,
      "bears_entering": bool,
      "stop_loss_pct": float,
      "take_profit_pct": float,
    }
"""

import logging

try:
    import CONFIG
except Exception:            # allow standalone import for testing
    class CONFIG:            # noqa: N801
        pass

log = logging.getLogger("strategy_v2")


# ──────────────────────────────────────────────────────────────────────
# Optional keyword news scorer.
# If your analyst.py already computes sentiment from your news feed,
# pass that number straight into analyze(); this helper is only a
# fallback for raw headlines.
# ──────────────────────────────────────────────────────────────────────
_BULL_WORDS = ("surge", "rally", "soar", "record high", "etf approval", "adoption",
               "partnership", "bullish", "upgrade", "inflow", "breakout", "buy the dip",
               "accumulation", "halving", "institutional")
_BEAR_WORDS = ("crash", "plunge", "dump", "hack", "exploit", "lawsuit", "sec sues",
               "ban", "bearish", "downgrade", "outflow", "liquidation", "sell-off",
               "selloff", "bankruptcy", "delist", "fud")


def score_headlines(headlines) -> float:
    """Crude keyword sentiment: returns a float in [-1.0, +1.0]."""
    if not headlines:
        return 0.0
    score = 0
    for h in headlines:
        t = (h or "").lower()
        score += sum(1 for w in _BULL_WORDS if w in t)
        score -= sum(1 for w in _BEAR_WORDS if w in t)
    # squash: 4+ net hits = fully bullish/bearish
    return max(-1.0, min(1.0, score / 4.0))


# ──────────────────────────────────────────────────────────────────────
class StrategyEngine:

    def __init__(self):
        self.min_confidence = getattr(CONFIG, "STRATEGY_MIN_CONFIDENCE", 65)
        self.allow_shorts   = getattr(CONFIG, "ALLOW_SHORTS", True)
        self.news_weight    = getattr(CONFIG, "NEWS_CONFIDENCE_WEIGHT", 15)
        self.news_veto      = getattr(CONFIG, "NEWS_VETO_THRESHOLD", 0.6)

    # ── regime ────────────────────────────────────────────────────────
    def detect_regime(self, ind: dict) -> dict:
        """
        BULL  : EMA20 > EMA50, price above EMA200, trend has strength
        BEAR  : EMA20 < EMA50, price below EMA200, trend has strength
        CHOP  : everything else
        bulls_entering: bullish structure + expanding MACD momentum +
                        above-average volume + OBV rising  (early flip)
        """
        close, e20, e50, e200 = ind["close"], ind["ema20"], ind["ema50"], ind["ema200"]
        adx        = ind.get("adx", 20.0)
        hist       = ind.get("macd_hist", 0.0)
        hist_prev  = ind.get("macd_hist_prev", 0.0)
        vol_ratio  = ind.get("vol_ratio", 1.0)
        obv_up     = ind.get("obv_trend") == "rising"
        ret_4h     = ind.get("ret_4h", 0.0)

        if e20 > e50 and close > e200 and adx >= 18:
            regime = "BULL"
        elif e20 < e50 and close < e200 and adx >= 18:
            regime = "BEAR"
        else:
            regime = "CHOP"

        bulls_entering = (
            e20 > e50
            and hist > 0 and hist > hist_prev          # MACD momentum expanding up
            and vol_ratio >= 1.15                      # volume coming in
            and (obv_up or ret_4h > 0)                 # buyers actually buying
        )
        bears_entering = (
            e20 < e50
            and hist < 0 and hist < hist_prev
            and vol_ratio >= 1.15
            and (not obv_up or ret_4h < 0)
        )
        return {"regime": regime,
                "bulls_entering": bulls_entering,
                "bears_entering": bears_entering}

    # ── strategy 1: the proven moneymaker ─────────────────────────────
    def _dip_reversal(self, ind, regime):
        """RSI + StochRSI double-oversold dip buy (87.5% WR historically)."""
        rsi, k = ind["rsi"], ind.get("stoch_k", 50)
        if not (rsi < 32 and k < 25):
            return None
        score, why = 55, [f"RSI({rsi:.0f})+StochRSI({k:.0f}) double-oversold"]
        if rsi < 20:
            score += 15; why.append("deep dip RSI<20 (best historical bucket)")
        if k < 10:
            score += 10; why.append("StochRSI floored")
        if ind.get("bb_pos", 0.5) < 0.08:
            score += 10; why.append("at lower Bollinger band")
        if ind.get("obv_trend") == "rising":
            score += 5;  why.append("OBV rising into the dip")
        if regime["regime"] == "BEAR":
            score -= 10; why.append("counter-trend (bear regime) -10")
        return {"action": "BUY", "strategy": "DIP_REVERSAL", "score": score,
                "why": why, "sl": 1.5, "tp": 4.0}

    # ── strategy 2: your original momentum logic, preserved ───────────
    def _trend_momentum(self, ind, regime):
        """
        Ported from your strategy.py. Same scoring skeleton, adapted to the
        live indicator feed. Historical MACD+TREND ran 19% WR, so the bar
        to actually fire is raised via extra confirmations, not lowered.
        """
        close, e20, e50 = ind["close"], ind["ema20"], ind["ema50"]
        if close < e20:
            return None                      # your rule: no longs below EMA20
        score, why = 0, []
        if close > e20 > e50:
            score += 25; why.append("uptrend (price>EMA20>EMA50)")
        hist, hist_prev = ind.get("macd_hist", 0), ind.get("macd_hist_prev", 0)
        if hist > 0 and hist_prev <= 0:
            score += 25; why.append("fresh bullish MACD cross")
        elif hist > 0:
            score += 10; why.append("MACD bullish")
        vol_ratio = ind.get("vol_ratio", 1.0)
        if vol_ratio > 1.5:
            score += 20; why.append(f"volume {vol_ratio:.1f}x avg")
        else:
            score -= 10; why.append("low volume")
        rsi = ind["rsi"]
        if 40 <= rsi < 60 and ind.get("bullish_candle"):
            score += 20; why.append("RSI rising through neutral zone")
        if ind.get("bb_pos", 0.5) < 0.1 and close > ind.get("bb_lower", 0):
            score += 10; why.append("lower-band bounce")
        if rsi > 70:
            score -= 30; why.append("RSI overbought")
        if regime["bulls_entering"]:
            score += 10; why.append("bulls entering (regime flip)")
        # historical 19% WR combo → require more than the generic minimum
        gate = max(self.min_confidence, 75)
        if score < gate:
            return None
        return {"action": "BUY", "strategy": "TREND_MOMENTUM", "score": score,
                "why": why, "sl": 1.5, "tp": 4.5}

    # ── strategy 3: bearish mirror of the dip (NEW) ───────────────────
    def _short_reversal(self, ind, regime):
        rsi, k = ind["rsi"], ind.get("stoch_k", 50)
        if not (rsi > 68 and k > 75):
            return None
        score, why = 55, [f"RSI({rsi:.0f})+StochRSI({k:.0f}) double-overbought"]
        if rsi > 80:
            score += 15; why.append("extreme overbought RSI>80")
        if ind.get("bb_pos", 0.5) > 0.92:
            score += 10; why.append("at upper Bollinger band")
        if regime["regime"] == "BULL":
            score -= 15; why.append("counter-trend (bull regime) -15")
        return {"action": "SELL", "strategy": "SHORT_REVERSAL", "score": score,
                "why": why, "sl": 1.5, "tp": 4.0}

    # ── strategy 4: bearish trend continuation (NEW) ──────────────────
    def _short_trend(self, ind, regime):
        close, e20, e50 = ind["close"], ind["ema20"], ind["ema50"]
        if not (close < e20 < e50):
            return None
        score, why = 25, ["downtrend (price<EMA20<EMA50)"]
        hist, hist_prev = ind.get("macd_hist", 0), ind.get("macd_hist_prev", 0)
        if hist < 0 and hist_prev >= 0:
            score += 25; why.append("fresh bearish MACD cross")
        elif hist < 0:
            score += 10; why.append("MACD bearish")
        if ind.get("vol_ratio", 1.0) > 1.5:
            score += 20; why.append("selling volume confirmed")
        else:
            score -= 10; why.append("low volume")
        rsi = ind["rsi"]
        if 45 <= rsi <= 60:
            score += 15; why.append("RSI rolled over from neutral")
        if rsi < 25:
            score -= 25; why.append("already oversold — bad short entry")
        if regime["bears_entering"]:
            score += 10; why.append("bears entering (regime flip)")
        gate = max(self.min_confidence, 75)
        if score < gate:
            return None
        return {"action": "SELL", "strategy": "SHORT_TREND", "score": score,
                "why": why, "sl": 1.5, "tp": 4.5}

    # ── main entry point ──────────────────────────────────────────────
    def analyze(self, symbol: str, market_data: dict,
                news_sentiment: float = None) -> dict:
        ind = (market_data or {}).get("indicators") or {}
        if not ind or not ind.get("close"):
            return self._hold("no market data", {})

        regime = self.detect_regime(ind)

        candidates = []
        for fn in (self._dip_reversal, self._trend_momentum):
            c = fn(ind, regime)
            if c:
                candidates.append(c)
        if self.allow_shorts:
            for fn in (self._short_reversal, self._short_trend):
                c = fn(ind, regime)
                if c:
                    candidates.append(c)

        if not candidates:
            return self._hold(
                f"no setup (regime={regime['regime']}"
                + (", bulls entering" if regime["bulls_entering"] else "")
                + (", bears entering" if regime["bears_entering"] else "") + ")",
                regime)

        best = max(candidates, key=lambda c: c["score"])

        # ── news adjustment ──
        if news_sentiment is not None and news_sentiment != 0:
            aligned = news_sentiment if best["action"] == "BUY" else -news_sentiment
            delta = round(aligned * self.news_weight)
            best["score"] += delta
            best["why"].append(f"news sentiment {news_sentiment:+.2f} → {delta:+d} conf")
            # strong opposite news vetoes the trade
            if aligned <= -self.news_veto:
                return self._hold(
                    f"{best['strategy']} setup vetoed by opposing news "
                    f"({news_sentiment:+.2f})", regime)

        confidence = max(0, min(100, best["score"]))
        if confidence < self.min_confidence:
            return self._hold(
                f"best={best['strategy']} conf {confidence} < {self.min_confidence}",
                regime)

        return {
            "action":          best["action"],
            "confidence":      confidence,
            "reasoning":       f"[{best['strategy']}] " + ", ".join(best["why"]),
            "strategy":        best["strategy"],
            "regime":          regime["regime"],
            "bulls_entering":  regime["bulls_entering"],
            "bears_entering":  regime["bears_entering"],
            "stop_loss_pct":   best["sl"],
            "take_profit_pct": best["tp"],
        }

    def _hold(self, reason: str, regime: dict) -> dict:
        return {
            "action": "HOLD", "confidence": 0, "reasoning": reason,
            "strategy": "NONE",
            "regime": regime.get("regime", "?"),
            "bulls_entering": regime.get("bulls_entering", False),
            "bears_entering": regime.get("bears_entering", False),
        }


# ──────────────────────────────────────────────────────────────────────
# Drop-in replacement for Analyst — same constructor and analyze()
# signature bot.py already uses. If you want your existing analyst.py
# (Claude calls, news feed, model.pkl) to keep running, don't use this
# shim — instead call engine.analyze(...) from inside analyst.py and
# blend its output with yours.
# ──────────────────────────────────────────────────────────────────────
class AnalystShim:
    def __init__(self, client=None, trader=None):
        self.client = client
        self.trader = trader
        self.engine = StrategyEngine()

    def analyze(self, symbol: str, market_data: dict) -> dict:
        # If you have a news score for this symbol, pass it here.
        return self.engine.analyze(symbol, market_data, news_sentiment=None)
