"""
Discord Reporter
Formats and sends all bot messages: signals, fills, stats, prices, errors.
"""

import logging
from datetime import datetime, timezone

import discord

log = logging.getLogger("reporter")

# Colour palette (decimal)
COLOR_BUY   = 0x2ECC71   # green
COLOR_SELL  = 0xE74C3C   # red
COLOR_HOLD  = 0x95A5A6   # grey
COLOR_STATS = 0x3498DB   # blue
COLOR_PRICE = 0xF39C12   # amber
COLOR_ERROR = 0xFF0000   # bright red


class DiscordReporter:
    def __init__(self, default_channel: discord.TextChannel):
        self._chan = default_channel

    async def _send(self, embed: discord.Embed, channel: discord.TextChannel | None = None):
        ch = channel or self._chan
        try:
            await ch.send(embed=embed)
        except Exception as e:
            log.error(f"Discord send failed: {e}")

    # ── Startup ───────────────────────────────────────────────────────────────
    async def send_startup_message(self, symbols: list[str], interval: int, budget: float = 10.0,
                                   session_start: int = 7, session_end: int = 17):
        em = discord.Embed(
            title="🤖 Crypto trading bot online",
            description=(
                f"**Watching:** {', '.join(symbols)}\n"
                f"**Cycle:** every {interval} minutes\n"
                f"**Mode:** Binance Testnet (paper trading)\n"
                f"**Budget:** ${budget:.2f} USDT (demo)\n"
                f"**AI:** Groq LLaMA 70B\n"
                f"**Active session:** {session_start:02d}:00 – {session_end:02d}:00 UTC (London + NY)\n\n"
                f"Type `!help` for available commands."
            ),
            color=COLOR_STATS,
            timestamp=datetime.now(timezone.utc),
        )
        await self._send(em)

    # ── Trade signal ──────────────────────────────────────────────────────────
    async def send_signal(self, symbol: str, decision: dict, market_data: dict):
        action     = decision.get("action", "HOLD")
        confidence = decision.get("confidence", 0)
        reasoning  = decision.get("reasoning", "")
        candles    = market_data.get("candles", [])
        price      = candles[-1]["close"] if candles else "N/A"

        color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL}.get(action, COLOR_HOLD)
        icon  = {"BUY": "🟢", "SELL": "🔴"}.get(action, "⚪")

        em = discord.Embed(
            title=f"{icon} {action} signal — {symbol}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        em.add_field(name="Price",      value=f"`${price:,.4f}`",       inline=True)
        em.add_field(name="Confidence", value=f"`{confidence}%`",       inline=True)
        em.add_field(name="Action",     value=f"**{action}**",          inline=True)
        em.add_field(name="Reasoning",  value=reasoning or "—",         inline=False)

        ind = market_data.get("indicators", {})
        if ind:
            ind_str = (
                f"RSI: `{ind.get('rsi', 'N/A')}` | "
                f"EMA20: `{ind.get('ema20', 'N/A')}` | "
                f"MACD: `{ind.get('macd', 'N/A')}`"
            )
            em.add_field(name="Indicators", value=ind_str, inline=False)

        sl  = decision.get("stop_loss_pct")
        tp  = decision.get("take_profit_pct")
        if sl and tp:
            em.add_field(name="Stop loss",    value=f"`{sl}%`",  inline=True)
            em.add_field(name="Take profit",  value=f"`{tp}%`",  inline=True)

        await self._send(em)

    # ── Partial take profit ───────────────────────────────────────────────────
    async def send_partial_tp(self, symbol: str, data: dict, channel=None):
        price      = data.get("price", 0)
        qty_closed = data.get("qty_closed", 0)
        pnl        = data.get("pnl", 0)
        tp1_price  = data.get("tp1_price", 0)
        pnl_sign   = "+" if pnl >= 0 else ""
        em = discord.Embed(
            title=f"💰 Partial TP hit — {symbol}",
            description="Closed **50%** of position at TP1. Stop loss moved to breakeven. Riding rest to full TP.",
            color=COLOR_BUY,
            timestamp=datetime.now(timezone.utc),
        )
        em.add_field(name="TP1 Price",    value=f"`${tp1_price:,.4f}`",          inline=True)
        em.add_field(name="Fill Price",   value=f"`${price:,.4f}`",              inline=True)
        em.add_field(name="Qty Closed",   value=f"`{qty_closed}`",               inline=True)
        em.add_field(name="Partial P&L",  value=f"`{pnl_sign}{pnl:.4f} USDT`",  inline=True)
        em.add_field(name="Remaining",    value="50% still open → riding to TP2", inline=False)
        await self._send(em, channel=channel)

    # ── Order fill ────────────────────────────────────────────────────────────
    async def send_order_fill(self, symbol: str, side: str, order: dict):
        sim      = order.get("simulated", False)
        exec_qty = float(order.get("executedQty", 0) or 0)
        quote    = float(order.get("cummulativeQuoteQty", 0) or 0)
        # Derive real fill price from quote/qty (works for testnet MARKET orders)
        if exec_qty > 0 and quote > 0:
            price = f"${quote / exec_qty:,.4f}"
        else:
            raw = order.get("price", "0")
            price = f"${float(raw):,.4f}" if raw and float(raw) > 0 else "N/A"
        qty   = order.get("executedQty", "N/A")
        oid   = order.get("orderId", "N/A")
        label = "📝 Paper order placed" if sim else "✅ Order filled"

        em = discord.Embed(title=label, color=COLOR_BUY if side == "BUY" else COLOR_SELL)
        em.add_field(name="Symbol",   value=symbol,          inline=True)
        em.add_field(name="Side",     value=f"**{side}**",   inline=True)
        em.add_field(name="Price",    value=f"`{price}`",    inline=True)
        em.add_field(name="Quantity", value=f"`{qty}`",      inline=True)
        em.add_field(name="Order ID", value=f"`{oid}`",      inline=True)
        await self._send(em)

    # ── P&L and accuracy stats ────────────────────────────────────────────────
    async def send_stats(self, stats: dict, channel=None):
        pnl      = stats.get("realized_pnl", 0)
        pnl_sign = "+" if pnl >= 0 else ""
        pnl_icon = "📈" if pnl >= 0 else "📉"

        em = discord.Embed(
            title=f"{pnl_icon} Performance summary",
            color=COLOR_STATS,
            timestamp=datetime.now(timezone.utc),
        )
        em.add_field(name="Total trades",    value=f"`{stats.get('total_trades', 0)}`",          inline=True)
        em.add_field(name="Wins / Losses",   value=f"`{stats.get('wins', 0)} / {stats.get('losses', 0)}`", inline=True)
        em.add_field(name="Accuracy",        value=f"`{stats.get('accuracy_pct', 0)}%`",         inline=True)
        em.add_field(name="Realised P&L",    value=f"`{pnl_sign}{pnl:.4f} USDT`",               inline=True)
        em.add_field(name="Open positions",  value=f"`{stats.get('open_positions', 0)}`",        inline=True)
        await self._send(em, channel=channel)

    # ── Open positions ────────────────────────────────────────────────────────
    async def send_positions(self, positions: list[dict], channel=None):
        if not positions:
            em = discord.Embed(title="📂 No open positions", color=COLOR_HOLD)
        else:
            em = discord.Embed(title=f"📂 Open positions ({len(positions)})", color=COLOR_STATS)
            for pos in positions:
                em.add_field(
                    name=pos["symbol"],
                    value=(
                        f"Side: **{pos['side']}**\n"
                        f"Entry: `{pos['entry']}`\n"
                        f"Qty: `{pos['quantity']}`"
                    ),
                    inline=True,
                )
        await self._send(em, channel=channel)

    # ── Live price update ─────────────────────────────────────────────────────
    async def send_price_update(self, prices: dict[str, float], channel=None):
        if not prices:
            return
        lines = [f"**{sym}:** `${price:,.4f}`" for sym, price in prices.items()]
        em = discord.Embed(
            title="💹 Live prices",
            description="\n".join(lines),
            color=COLOR_PRICE,
            timestamp=datetime.now(timezone.utc),
        )
        await self._send(em, channel=channel)

    # ── Error ─────────────────────────────────────────────────────────────────
    async def send_error(self, symbol: str, error: str):
        em = discord.Embed(
            title=f"⚠️ Error — {symbol}",
            description=f"```{error[:500]}```",
            color=COLOR_ERROR,
        )
        await self._send(em)
