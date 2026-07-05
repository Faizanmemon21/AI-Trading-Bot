"""
Analyst — Market analysis engine
Runs indicator-based signals + optional Claude confirmation.
Works fully without an Anthropic API key.
"""

import json
import logging
import os
import CONFIG

log = logging.getLogger("analyst")


class Analyst:
    def __init__(self, client, trader):
        self.client = client        # May be None if no API key
        self.trader = trader

        try:
            from ml_filter import MLFilter
            self.ml_filter = MLFilter()
        except Exception:
            self.ml_filter = None

        mode = "Claude + Indicators" if client else "Indicators only"
        ml   = (self.ml_filter.available if self.ml_filter else False)
        log.info(f"✅ Analyst initialized | Mode: {mode} | ML filter: {ml}")

    # ─────────────────────────────────────────────────────────────────
    # PUBLIC
    # ─────────────────────────────────────────────────────────────────

    def analyze(self, symbol: str, market_data: dict) -> dict:
        """Main entry point — returns BUY / SELL / HOLD decision."""

        if self.trader.is_blacklisted(symbol):
            return {"action": "HOLD", "confidence": 0, "reasoning": "Blacklisted"}

        indicators = market_data.get("indicators", {})
        if not indicators:
            return {"action": "HOLD", "confidence": 0, "reasoning": "No indicators"}

        # Step 1 — indicator confluence score
        signals    = self._compute_signals(symbol, indicators)
        confluence = signals["confluence"]

        log.info(
            f"{symbol} | confluence={confluence} | signals={signals['reasoning']}"
        )

        if confluence < CONFIG.MIN_CONFLUENCE_SCORE:
            log.info(f"{symbol} BLOCKED: confluence {confluence} < {CONFIG.MIN_CONFLUENCE_SCORE}")
            return {
                "action":     "HOLD",
                "confidence": confluence,
                "reasoning":  f"Low confluence ({confluence}/{CONFIG.MIN_CONFLUENCE_SCORE}). {signals['reasoning']}",
            }

        # Step 1.5 — ML filter (Stage 10: model.pkl finally wired in).
        # It was loaded in __init__ since Stage 6 but predict() was never
        # called anywhere. Runs in "shadow" mode first (logs p(win), blocks
        # nothing) so you can calibrate ML_CONFIDENCE_THRESHOLD on real data,
        # then flip CONFIG.ML_MODE = "gate" to let it veto trades.
        ml_prob = None
        if (self.ml_filter and self.ml_filter.available
                and getattr(CONFIG, "ENABLE_ML_FILTER", True)):
            ml_prob   = self.ml_filter.predict(indicators)
            mode      = getattr(CONFIG, "ML_MODE", "shadow")
            threshold = getattr(CONFIG, "ML_CONFIDENCE_THRESHOLD", 0.40)
            log.info(f"{symbol} | ML p(win)={ml_prob:.3f} (mode={mode}, gate={threshold})")
            if mode == "gate" and ml_prob < threshold:
                log.info(f"{symbol} BLOCKED by ML filter: {ml_prob:.3f} < {threshold}")
                return {
                    "action":     "HOLD",
                    "confidence": confluence,
                    "reasoning":  f"ML veto p={ml_prob:.2f} | {signals['reasoning']}",
                    "ml_prob":    ml_prob,
                }

        # Step 2 — ask Claude (optional)
        decision = self._ask_claude(symbol, market_data, signals)
        if ml_prob is not None:
            decision["ml_prob"] = ml_prob

        log.info(
            f"{symbol} → {decision['action']} conf={decision.get('confidence')} | "
            f"{decision.get('reasoning','')[:70]}"
        )
        return decision

    # ─────────────────────────────────────────────────────────────────
    # SIGNAL COMPUTATION
    # ─────────────────────────────────────────────────────────────────

    def _compute_signals(self, symbol: str, ind: dict) -> dict:
        score       = 0
        signals_hit = []

        # Rule 1 — EMA trend
        if CONFIG.RULES.get("uptrend_ema"):
            price = ind.get("close", 0)
            ema20 = ind.get("ema20", 0) or 1
            ema50 = ind.get("ema50", 0) or 1
            if price > ema20 > ema50:
                score += CONFIG.RULE_WEIGHTS.get("uptrend_ema", 30)
                signals_hit.append("uptrend")
            elif price > ema20:
                # Stage 10: this half-credit branch went 0W/9L in live trades.
                # Its weight is now a CONFIG knob (WEAK_TREND_MULTIPLIER,
                # default 0.0 = still logged in reasoning, scores nothing).
                mult = getattr(CONFIG, "WEAK_TREND_MULTIPLIER", 0.0)
                pts  = int(CONFIG.RULE_WEIGHTS.get("uptrend_ema", 30) * mult)
                if pts > 0:
                    score += pts
                signals_hit.append("price>EMA20")

        # Rule 2 — RSI oversold
        if CONFIG.RULES.get("rsi_oversold"):
            rsi = ind.get("rsi", 50)
            if rsi < 40:
                score += CONFIG.RULE_WEIGHTS.get("rsi_oversold", 20)
                signals_hit.append(f"RSI({rsi:.0f})")

        # Rule 3 — MACD bullish
        if CONFIG.RULES.get("macd_bullish"):
            macd        = ind.get("macd", 0) or 0
            macd_signal = ind.get("macd_signal", 0) or 0
            macd_hist   = ind.get("macd_hist", 0) or 0
            if macd_hist > 0 and macd > macd_signal:
                score += CONFIG.RULE_WEIGHTS.get("macd_bullish", 25)
                signals_hit.append("MACD+")
            elif macd > macd_signal:
                score += int(CONFIG.RULE_WEIGHTS.get("macd_bullish", 25) * 0.5)
                signals_hit.append("MACD↑")

        # Rule 4 — StochRSI oversold
        if CONFIG.RULES.get("stoch_rsi_extreme"):
            stoch_k = ind.get("stoch_k", 50)
            if stoch_k < 30:
                score += CONFIG.RULE_WEIGHTS.get("stoch_rsi_extreme", 15)
                signals_hit.append(f"StochRSI({stoch_k:.0f})")

        # Rule 5 — OBV rising
        if CONFIG.RULES.get("obv_rising"):
            if ind.get("obv_trend") == "rising":
                score += CONFIG.RULE_WEIGHTS.get("obv_rising", 10)
                signals_hit.append("OBV↑")

        # Stage 10 combo bonus — RSI oversold + StochRSI floor firing TOGETHER
        # went 7W/1L (88% WR, +$52.80) across the last 45 live trades. Reward it.
        has_rsi   = any(s.startswith("RSI(") for s in signals_hit)
        has_stoch = any(s.startswith("StochRSI(") for s in signals_hit)
        if has_rsi and has_stoch:
            bonus = getattr(CONFIG, "COMBO_BONUS_RSI_STOCH", 0)
            if bonus:
                score += bonus
                signals_hit.append("COMBO")

        reasoning = ", ".join(signals_hit) if signals_hit else "no signals"
        return {"confluence": int(min(100, score)), "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────
    # CLAUDE (OPTIONAL)
    # ─────────────────────────────────────────────────────────────────

    def _ask_claude(self, symbol: str, market_data: dict, signals: dict) -> dict:
        """Asks Claude for confirmation. Falls back to indicator decision if unavailable."""
        if not self.client:
            return self._indicator_decision(signals, market_data)

        candles    = market_data.get("candles", [])
        indicators = market_data.get("indicators", {})

        if len(candles) < 20:
            return self._indicator_decision(signals, market_data)

        prompt = self._build_prompt(symbol, candles, indicators, signals)
        system = (
            "You are a crypto trading analyst. "
            "Return ONLY a JSON object with keys: "
            "action (BUY, SELL, or HOLD), "
            "confidence (integer 0-100), "
            "reasoning (one sentence string), "
            "stop_loss_pct (number), "
            "take_profit_pct (number). "
            "No markdown, no explanation, just the JSON."
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                system=system,
                messages=[{"role": "user", "content": prompt}]
            )
            text  = response.content[0].text
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
        except Exception as e:
            log.warning(f"Claude error for {symbol}: {e} — using indicators")

        return self._indicator_decision(signals, market_data)

    def _indicator_decision(self, signals: dict, market_data: dict) -> dict:
        """Pure indicator-based BUY/HOLD decision (no Claude required)."""
        confluence = signals.get("confluence", 0)
        reasoning  = signals.get("reasoning", "")
        rsi        = market_data.get("indicators", {}).get("rsi", 50)

        if confluence >= CONFIG.MIN_CONFLUENCE_SCORE and rsi < 70:
            return {
                "action":          "BUY",
                "confidence":      min(85, confluence + 10),
                "reasoning":       f"Indicators: {reasoning}",
                "stop_loss_pct":   CONFIG.STOP_LOSS_PCT,
                "take_profit_pct": CONFIG.TAKE_PROFIT_PCT,
            }
        return {
            "action":     "HOLD",
            "confidence": confluence,
            "reasoning":  f"Confluence {confluence} | {reasoning}",
        }

    def _build_prompt(self, symbol, candles, ind, signals):
        price  = ind.get("close", 0)
        rsi    = ind.get("rsi", 50)
        ema20  = ind.get("ema20", 0)
        ema50  = ind.get("ema50", 0)
        macd   = ind.get("macd", 0)
        mhist  = ind.get("macd_hist", 0)
        stoch  = ind.get("stoch_k", 50)
        obv    = ind.get("obv_trend", "neutral")
        vol    = ind.get("vol_ratio", 1.0)

        last5 = candles[-5:]
        cdl   = " | ".join(
            f"C:{c['close']:.2f}" for c in last5
        )

        # Stage 10: feed past-performance context back into the prompt.
        # memory.build_prompt_context() existed since Stage 4 but was never
        # actually included here — the "learning" loop was disconnected.
        try:
            from memory import build_prompt_context
            perf_ctx = build_prompt_context(self.trader.trade_history)
        except Exception:
            perf_ctx = ""

        prompt = (
            f"{symbol} @ ${price:.4f}\n"
            f"Confluence: {signals['confluence']}/100 — {signals['reasoning']}\n"
            f"RSI:{rsi:.0f} EMA20:{ema20:.2f} EMA50:{ema50:.2f} "
            f"MACD:{macd:+.4f}(hist:{mhist:+.4f}) "
            f"StochRSI:{stoch:.0f} OBV:{obv} Vol:{vol:.1f}x\n"
            f"Last 5 closes: {cdl}\n"
        )
        if perf_ctx:
            prompt += perf_ctx + "\n"
        prompt += "Should I BUY, SELL, or HOLD? Return JSON only."
        return prompt

    def build_performance_context(self, trade_history: list) -> str:
        closed = [t for t in trade_history if t.get("exit") is not None]
        if len(closed) < 5:
            return ""
        recent = closed[-20:]
        wins   = sum(1 for t in recent if t.get("pnl", 0) >= 0)
        pnl    = sum(t.get("pnl", 0) for t in recent)
        wr     = round(wins / len(recent) * 100) if recent else 0
        return f"Recent: {len(recent)} trades, {wr}% win rate, {pnl:+.2f} USDT."
