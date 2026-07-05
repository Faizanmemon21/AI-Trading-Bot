"""
CONFIG.py — Stage 10: Data-Driven Tightening ($100 capital, leverage unchanged)

WHAT THE LAST 45 LIVE TRADES ACTUALLY SAID (current-era, Jun 24 – Jul 04):

  SIGNAL PERFORMANCE (tag present in trade reasoning):
    RSI + StochRSI together:  7W/1L  = 88% WR  +$52.80  <- THE EDGE
    StochRSI alone:           3W/2L  = 60% WR  +$28.35  <- good
    RSI(0-20) deep oversold:  4W/0L  = 100% WR +$37.40  <- deep beats shallow
    RSI(30-40) shallow:       2W/3L  = 40% WR           <- weak alone
    uptrend (full EMA stack): 8W/7L  = 53% WR           <- context only
    price>EMA20 (half-credit):0W/9L  =  0% WR  -$2.13   <- POISON, weight now 0
    OBV rising:               3W/15L = 17% WR           <- stays OFF (confirmed)
    MACD+:                    1W/10L =  9% WR           <- stays OFF (confirmed)

  COIN PERFORMANCE (current era):
    SOLUSDT:  15 trades, 67% WR, +$108.07, PF 4.45  <- carries the whole bot
    LTCUSDT:   6 trades, 50% WR,   +$3.63
    UNIUSDT:  14 trades, 36% WR,   -$0.13           <- churns, tiny size now
    ETH/BNB/BTC/AAVE: 0% WR combined                <- tiny size now

  KEY LEAK FIXED: "uptrend"-only entries (confluence exactly 20) kept
  slipping through the old MIN_CONFLUENCE_SCORE=20 gate — the last four
  losses (-7.49, -7.88, -2.27, -2.44) were all trend-only or OBV-only
  entries. Gate is now 50: StochRSI can still trade alone, trend cannot.

GOAL: same win frequency on the good setups, fewer weak entries,
loser size cut ~10x on unproven coins via per-symbol tiering.
"""

# ============================================================
# RISK MANAGEMENT  (leverage untouched, as requested)
# ============================================================

USE_LEVERAGE           = True
LEVERAGE_MULTIPLIER    = 75
BASE_POSITION_PCT      = 5.0      # 5% = $5 margin on $100 -> $150 notional @30x
LEVERAGED_POSITION_PCT = 3      # 0.5% = $0.50 margin -> $15 notional @30x

# Per-symbol tiering (Stage 10 — now actually implemented in trader.py):
# coins listed here get BASE_POSITION_PCT, everything else gets
# LEVERAGED_POSITION_PCT. Promote a coin only after it proves itself.
PRIMARY_SYMBOLS = "SOLUSDT"

STOP_LOSS_PCT          = 1.5
TAKE_PROFIT_PCT        = 4.0

# Daily loss guard — RE-ENABLED in trader.py (was a no-op since Stage 8).
# Set ENABLE_DAILY_LOSS_GUARD = False to restore "never halt" behaviour.
ENABLE_DAILY_LOSS_GUARD   = True
MAX_DAILY_LOSS_PCT        = 5.0   # $5 max daily loss on $100
DAILY_HALT_DURATION_HOURS = 24

# Circuit breaker — NOW WIRED UP in trader.py (existed since Stage 9, unused)
MAX_CONSECUTIVE_LOSSES  = 5
CONSECUTIVE_LOSS_HALT_H = 4

# ============================================================
# ML FILTER  (model.pkl — finally connected in analyst.py)
# ============================================================
# Your Colab model (RF+XGB, 14 coins, 25 features, label = "hits +3%
# before -1.5%") was loaded every run but predict() was NEVER called.
#
# ML_MODE:
#   "shadow" -> logs p(win) on every signal, blocks NOTHING (start here,
#               run 2-3 days, look at p(win) of winners vs losers in logs)
#   "gate"   -> blocks any entry with p(win) < ML_CONFIDENCE_THRESHOLD
#   "off"    -> skip prediction entirely
#
# NOTE: because the label ("+3% before -1.5%") has a low base rate,
# typical p(win) values sit around 0.2-0.4, NOT around 0.5. The old
# 0.55 threshold would have vetoed everything. Calibrate from shadow
# logs before gating. 0.40 is a starting suggestion only.
ENABLE_ML_FILTER        = True
ML_MODE                 = "shadow"
ML_CONFIDENCE_THRESHOLD = 0.40

# ============================================================
# SIGNAL RULES — nothing removed, weights retuned from live data
# ============================================================

RULES = {
    "uptrend_ema":       True,    # Context filter only (53% WR alone)
    "macd_bullish":      False,   # 9% WR live — stays OFF
    "volume_gate":       False,
    "rsi_oversold":      True,    # 88% WR when paired with StochRSI
    "stoch_rsi_extreme": True,    # PRIMARY — 77% WR whenever present
    "obv_rising":        False,   # 17% WR live — stays OFF
    "high_volume_spike": False,
    "bollinger_bounce":  False,
}

RULE_WEIGHTS = {
    "uptrend_ema":       20,
    "macd_bullish":       0,   # OFF
    "rsi_oversold":      30,
    "stoch_rsi_extreme": 50,   # PRIMARY
    "obv_rising":         0,   # OFF
}

# Stage 10 additions:
# Bonus when RSI oversold AND StochRSI floor fire together (7W/1L live).
COMBO_BONUS_RSI_STOCH = 20
# Multiplier for the price>EMA20 half-credit branch (0W/9L live).
# 0.0 = still logged in reasoning, contributes no score. Old behaviour: 0.5.
WEAK_TREND_MULTIPLIER = 0.0

# Gate raised 20 -> 50. What can trade now:
#   StochRSI alone (50)                    -> passes  (60% WR live)
#   StochRSI + uptrend (70)                -> passes
#   RSI + StochRSI + COMBO (100)           -> passes  (88% WR live)
#   RSI alone (30)                         -> BLOCKED (25% WR live)
#   uptrend alone (20)                     -> BLOCKED (recent losses)
#   price>EMA20 alone (0)                  -> BLOCKED (0% WR live)
ML_CONFIDENCE_THRESHOLD_LEGACY = 0.55   # kept for reference
MIN_CONFLUENCE_SCORE           = 50

# ============================================================
# COINS — list unchanged; sizing tiering does the risk control now.
# SOL trades at 5%, everything else probes at 0.5% until it earns
# a spot in PRIMARY_SYMBOLS.
# ============================================================

SYMBOLS = "SOLUSDT,UNIUSDT,LINKUSDT,AAVEUSDT,LTCUSDT,BNBUSDT"

# ============================================================
# POSITION LIMITS
# ============================================================

MAX_OPEN_POSITIONS = 4
MAX_SAME_COIN      = 1

# ============================================================
# SESSION — 24/7
# ============================================================

TRADING_SESSION_START = 0
TRADING_SESSION_END   = 24

# ============================================================
# BLACKLIST  (still disabled in trader.py per your earlier choice)
# ============================================================

BLACKLIST_AFTER_LOSSES   = 2
BLACKLIST_DURATION_HOURS = 6
COOLOFF_AFTER_DAILY_MAX  = True
COOLOFF_DURATION_HOURS   = 12

# ============================================================
# EXECUTION
# ============================================================

INTERVAL_MINS = 15

# ============================================================
# KELLY
# ============================================================

USE_KELLY_SIZING    = False
KELLY_SAFETY_FACTOR = 0.25

# ============================================================
# CAPITAL — $100 TEST
# ============================================================

USE_TESTNET    = True
TESTNET_BUDGET = 100.0
LIVE_BUDGET    = 100.0
LIVE_LEVERAGE  = False

# ============================================================
# LOGGING
# ============================================================

LOG_LEVEL            = "INFO"
SEND_DISCORD_UPDATES = False
SEND_EVERY_N_CYCLES  = 1

# ═══════════════════════════════════════════════════════════════════
#  STAGE 11 — paste this block into your CONFIG.py
#  (replace any of these names that already exist there)
# ═══════════════════════════════════════════════════════════════════

# ── LEVERAGE (as requested: 75x) ──────────────────────────────────────
USE_LEVERAGE        = True
LEVERAGE_MULTIPLIER = 75          # was 30

# Honest-mode liquidation simulation. At 75x a position is liquidated
# after roughly a (100/75 − maintenance) ≈ 0.8% move against entry —
# which is INSIDE the 1.5% stop loss, so on a real futures account the
# stop never fires; every loser is a full-margin loss. Your own history
# replayed at 75x: 18 of 39 trades liquidate, including 11 trades that
# were WINNERS at 30x, net ≈ −102% of margin per trade. Leaving this
# True keeps the testnet numbers honest; setting it False brings back
# fantasy-mode PnL that live trading cannot reproduce.
SIMULATE_LIQUIDATION = True
SIM_MAINT_MARGIN_PCT = 0.5        # maintenance margin used by the model

# NOTE: on real Binance Futures, 75x is only offered on a handful of
# majors (BTC/ETH tier). Most of your 15 alts cap at 20–50x, and the cap
# drops further as position size grows. The simulator will happily do
# 75x on UNIUSDT; the real exchange will not.

# ── SIZING ────────────────────────────────────────────────────────────
# Margin per trade stays the same as before; leverage only scales the
# notional. At 75x with SIMULATE_LIQUIDATION on, expect each losing
# trade to cost the FULL margin below.
# BASE_POSITION_PCT      = 5.0    # (keep your existing values)
# LEVERAGED_POSITION_PCT = 0.5

# ── GUARDS (unblocked, as requested) ──────────────────────────────────
# This is what halted your bot on 2026-07-05 (daily −5.16 vs −5.00 limit)
# and what the "2 losses in a row" cool-off would use. Both OFF now.
# The code paths still exist — flip these back any time. For the record:
# your bot once survived a 17-loss streak and still ended +120 USDT, so
# streak halts are optional; at 75x, though, a guard is the only thing
# standing between one bad hour and a zeroed account.
ENABLE_DAILY_LOSS_GUARD  = False   # was True (halt at −MAX_DAILY_LOSS_PCT%/day)
MAX_DAILY_LOSS_PCT       = 5.0     # only used if guard re-enabled
MAX_CONSECUTIVE_LOSSES   = 0       # 0 = streak cool-off disabled
CONSECUTIVE_LOSS_HALT_H  = 4

# ── EXIT MANAGEMENT (new) ─────────────────────────────────────────────
# Once a trade is up TRAIL_ACTIVATE_PCT, the stop moves to
# entry + TRAIL_LOCK_PCT so a winner can no longer become a loser.
# (Your UNI trade was +2.4% before dying at the −1.5% stop.)
TRAIL_ACTIVATE_PCT = 2.0
TRAIL_LOCK_PCT     = 0.3           # set TRAIL_ACTIVATE_PCT = 0 to disable

# ── STRATEGY ENGINE (strategy_v2.py) ─────────────────────────────────
STRATEGY_MIN_CONFIDENCE = 65       # floor for any strategy to fire
MIN_CONFIDENCE_TO_TRADE = 20       # bot.py order gate (unchanged behaviour)
ALLOW_SHORTS            = True     # SHORT_REVERSAL / SHORT_TREND enabled
                                   # (spot testnet fakes shorts via paper
                                   # fills — real shorting needs the
                                   # FUTURES testnet API, different URLs)

# ── NEWS SENTIMENT HOOK ───────────────────────────────────────────────
# Pass a per-symbol score in [−1.0 … +1.0] into
# StrategyEngine.analyze(symbol, market_data, news_sentiment=score).
NEWS_CONFIDENCE_WEIGHT = 15        # max confidence points news can add/remove
NEWS_VETO_THRESHOLD    = 0.6       # opposite news ≥ this strength blocks trade

# ═══════════════════════════════════════════════════════════════════
#  ALTERNATIVE PRESET — high leverage that history says survives
#  (kept here commented out; swap in if 75x drains the testnet)
# ═══════════════════════════════════════════════════════════════════
# LEVERAGE_MULTIPLIER    = 20      # liq at ~4.5% — outside the 1.5% SL,
#                                  # so stops work and dips survive
# ENABLE_DAILY_LOSS_GUARD = True
# MAX_DAILY_LOSS_PCT      = 10.0   # looser than before, but a floor exists
# MAX_CONSECUTIVE_LOSSES  = 6      # above normal variance, below disaster
