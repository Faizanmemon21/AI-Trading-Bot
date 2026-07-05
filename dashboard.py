"""
Dashboard Server — Clean Loveable-style with BTC/ETH/SOL charts
Tabs: Overview | Positions | Signals | History
"""

import json, os, threading, asyncio, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

try:
    import CONFIG
    BUDGET = CONFIG.TESTNET_BUDGET
except Exception:
    BUDGET = float(os.getenv("TESTNET_BUDGET", "10000"))

app = Flask(__name__)
CORS(app)

state = {
    "stats":        {"total_trades":0,"wins":0,"losses":0,"realized_pnl":0.0,"accuracy_pct":0,"open_positions":0},
    "positions":    [], "prices":{}, "signals":[], "trade_history":[],
    "last_updated": None, "bot_online": False, "daily_pnl": 0.0,
}
state_lock = threading.Lock()

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoBot Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --void:#07090c;--panel:#0d1117;--panel2:#121920;--panel3:#18212a;
  --line:#1c2430;--line2:#243040;
  --signal:#00e1b4;--signal-dim:rgba(0,225,180,.1);--signal-glow:rgba(0,225,180,.22);
  --win:#3ee08c;--win-dim:rgba(62,224,140,.1);
  --loss:#ff5a5f;--loss-dim:rgba(255,90,95,.1);
  --gold:#f0b429;--blue:#58a6ff;--purple:#bc8cff;
  --ink:#eef3f7;--text:#b0bec5;--muted:#607080;--faint:#3d4f60;
  --radius:14px;--radius-sm:9px;
}
html{scroll-behavior:smooth}
body{background:var(--void);color:var(--text);font-family:'Inter',system-ui,sans-serif;min-height:100vh;font-size:13px;
  background-image:radial-gradient(ellipse 60% 40% at 10% -10%,rgba(0,225,180,.05) 0%,transparent 60%),
    radial-gradient(ellipse 50% 50% at 90% 5%,rgba(88,166,255,.04) 0%,transparent 55%);
  background-attachment:fixed}
.mono{font-family:'JetBrains Mono',monospace}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--line2);border-radius:3px}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(62,224,140,.6)}70%{box-shadow:0 0 0 7px rgba(62,224,140,0)}100%{box-shadow:0 0 0 0 rgba(62,224,140,0)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes rowGlow{from{background:rgba(0,225,180,.08)}to{background:transparent}}
@keyframes tickScroll{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── Header ─────────────────────────────────────────────────── */
header{display:flex;align-items:center;justify-content:space-between;padding:14px 26px;
  background:rgba(13,17,23,.9);border-bottom:1px solid var(--line);
  position:sticky;top:0;z-index:200;backdrop-filter:blur(16px)}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{width:36px;height:36px;background:linear-gradient(135deg,var(--signal),#009e7a);
  border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;
  box-shadow:0 0 20px var(--signal-glow)}
.logo-text h1{font-family:'Space Grotesk',sans-serif;font-size:15px;font-weight:700;color:var(--ink);letter-spacing:.4px}
.logo-text p{font-size:9px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-top:1px}
.header-right{display:flex;align-items:center;gap:12px}
.capital-badge{display:flex;align-items:center;gap:7px;padding:6px 14px;border-radius:20px;
  background:var(--signal-dim);border:1px solid rgba(0,225,180,.3);
  font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--signal);font-weight:600}
.capital-badge span{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:1px}
.status-pill{display:flex;align-items:center;gap:7px;padding:6px 14px;border-radius:20px;
  background:var(--panel2);border:1px solid var(--line2);
  font-size:11px;font-family:'JetBrains Mono',monospace;color:var(--text)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint);transition:background .3s}
.dot.online{background:var(--win);animation:pulse 2s infinite}
#update-time{font-size:10px;color:var(--faint);font-family:'JetBrains Mono',monospace}

/* ── Ticker ──────────────────────────────────────────────────── */
.ticker-wrap{background:var(--panel);border-bottom:1px solid var(--line);overflow:hidden;
  height:30px;display:flex;align-items:center;position:relative}
.ticker-wrap::before,.ticker-wrap::after{content:'';position:absolute;top:0;bottom:0;width:60px;z-index:2;pointer-events:none}
.ticker-wrap::before{left:0;background:linear-gradient(90deg,var(--panel),transparent)}
.ticker-wrap::after{right:0;background:linear-gradient(270deg,var(--panel),transparent)}
.ticker-track{display:flex;white-space:nowrap;animation:tickScroll 36s linear infinite}
.ticker-wrap:hover .ticker-track{animation-play-state:paused}
.ti{display:inline-flex;align-items:center;gap:6px;padding:0 16px;
  font-family:'JetBrains Mono',monospace;font-size:10.5px;border-right:1px solid var(--line);color:var(--text)}
.ti-sym{color:var(--muted);font-weight:700}.ti-px{color:var(--ink);font-weight:600}.ti-arr{font-size:8px;font-weight:700}
@keyframes flashUp{0%{background:rgba(62,224,140,.12)}100%{background:transparent}}
@keyframes flashDn{0%{background:rgba(255,90,95,.1)}100%{background:transparent}}
.flash-up{animation:flashUp 1s ease}.flash-dn{animation:flashDn 1s ease}

/* ── Tabs ────────────────────────────────────────────────────── */
.tab-nav{display:flex;align-items:center;gap:2px;padding:10px 22px 0;
  background:var(--panel);border-bottom:1px solid var(--line);
  position:sticky;top:61px;z-index:150;backdrop-filter:blur(12px)}
.tab-btn{display:flex;align-items:center;gap:7px;background:none;
  border:none;border-bottom:2px solid transparent;padding:9px 18px 11px;margin-bottom:-1px;
  color:var(--muted);font-family:'Inter',sans-serif;font-size:12.5px;font-weight:500;
  cursor:pointer;transition:color .2s,border-color .2s}
.tab-btn:hover{color:var(--text)}.tab-btn.active{color:var(--signal);border-bottom-color:var(--signal);font-weight:600}
.tab-badge{background:var(--panel3);color:var(--muted);border-radius:20px;
  padding:1px 7px;font-size:9.5px;font-weight:700;font-family:'JetBrains Mono',monospace;border:1px solid var(--line2)}
.tab-badge.green{background:var(--win-dim);color:var(--win);border-color:rgba(62,224,140,.25)}
.tab-pane{display:none}.tab-pane.active{display:block;animation:fadeUp .25s ease}

/* ── Layout ──────────────────────────────────────────────────── */
main{padding:18px 22px 36px;max-width:1800px;margin:0 auto;display:grid;gap:14px}

/* ── Stat cards ──────────────────────────────────────────────── */
.cards-row{display:grid;gap:10px}
.row-6{grid-template-columns:repeat(6,1fr)}
.row-5{grid-template-columns:repeat(5,1fr)}
@media(max-width:1300px){.row-6{grid-template-columns:repeat(3,1fr)}.row-5{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.row-6,.row-5{grid-template-columns:repeat(2,1fr)}}
.card{background:var(--panel2);border:1px solid var(--line);border-radius:var(--radius);
  padding:16px 18px;position:relative;overflow:hidden;transition:transform .2s,border-color .25s,box-shadow .25s}
.card:hover{transform:translateY(-2px);border-color:var(--line2)}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--line)}
.card.c-signal::before{background:linear-gradient(90deg,var(--signal),transparent)}
.card.c-signal:hover{box-shadow:0 6px 24px rgba(0,225,180,.1)}
.card.c-green::before{background:linear-gradient(90deg,var(--win),transparent)}
.card.c-green:hover{box-shadow:0 6px 24px rgba(62,224,140,.1)}
.card.c-red::before{background:linear-gradient(90deg,var(--loss),transparent)}
.card.c-blue::before{background:linear-gradient(90deg,var(--blue),transparent)}
.card.c-gold::before{background:linear-gradient(90deg,var(--gold),transparent)}
.card.c-purple::before{background:linear-gradient(90deg,var(--purple),transparent)}
.card .c-label{font-size:9.5px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted);margin-bottom:11px;font-weight:600}
.card .c-value{font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:700;
  color:var(--ink);line-height:1;letter-spacing:-.5px;transition:color .3s}
.card .c-sub{font-size:10px;color:var(--faint);margin-top:7px}
.card.c-signal .c-value{color:var(--signal)}.card.c-green .c-value{color:var(--win)}
.card.c-red .c-value{color:var(--loss)}.card.c-blue .c-value{color:var(--blue)}
.card.c-gold .c-value{color:var(--gold)}.card.c-purple .c-value{color:var(--purple)}
.card.capital-card{background:linear-gradient(135deg,rgba(0,225,180,.07),var(--panel2) 70%)}
.card.capital-card::before{background:linear-gradient(90deg,var(--signal),#00c4ff,transparent);height:3px}

/* ── Panel ───────────────────────────────────────────────────── */
.panel{background:var(--panel2);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
.panel-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:12px 18px;border-bottom:1px solid var(--line);background:rgba(0,0,0,.12)}
.panel-hdr h2{font-family:'Space Grotesk',sans-serif;font-size:11px;font-weight:600;
  text-transform:uppercase;letter-spacing:1.6px;color:var(--text)}
.badge{display:inline-flex;align-items:center;gap:4px;background:var(--panel3);
  border:1px solid var(--line2);border-radius:20px;font-family:'JetBrains Mono',monospace;
  padding:2px 9px;font-size:10px;color:var(--muted);font-weight:600}
.badge.live{border-color:rgba(0,225,180,.4);color:var(--signal)}
.badge.live::before{content:'●';font-size:7px;animation:pulse 2s infinite}

/* ── Charts ──────────────────────────────────────────────────── */
.tf-group{display:flex;gap:3px;background:var(--panel3);border-radius:8px;padding:3px;border:1px solid var(--line)}
.tf-btn{background:none;border:none;padding:4px 14px;border-radius:6px;
  color:var(--muted);font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;cursor:pointer;transition:all .2s}
.tf-btn:hover{color:var(--text)}.tf-btn.active{background:var(--signal-dim);color:var(--signal);border:1px solid rgba(0,225,180,.3)}
.charts-row{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line)}
@media(max-width:1100px){.charts-row{grid-template-columns:1fr}}
.chart-wrap{border-right:1px solid var(--line);overflow:hidden;min-width:0}
.chart-wrap:last-child{border-right:none}
.cw-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:11px 16px 9px;border-bottom:1px solid var(--line);background:rgba(0,0,0,.1)}
.cw-left{display:flex;align-items:baseline;gap:10px}
.cw-sym{font-family:'Space Grotesk',sans-serif;font-size:14px;font-weight:700}
.cw-sym.gold{color:var(--gold)}.cw-sym.blue{color:var(--blue)}.cw-sym.purple{color:var(--purple)}
.cw-price{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:var(--ink)}
.cw-meta{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.cw-chg{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;padding:2px 8px;border-radius:5px}
.cw-chg.pos{color:var(--win);background:var(--win-dim)}.cw-chg.neg{color:var(--loss);background:var(--loss-dim)}.cw-chg.flat{color:var(--faint)}
.cw-vol{font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--faint)}
.chart-loading{display:flex;align-items:center;justify-content:center;height:300px;
  color:var(--muted);font-size:11px;font-family:'JetBrains Mono',monospace;flex-direction:column;gap:10px}
.chart-loading::before{content:'';width:22px;height:22px;border:2px solid var(--line2);
  border-top-color:var(--signal);border-radius:50%;animation:spin .8s linear infinite}
.cw-chart{height:300px}

/* ── Grid helpers ────────────────────────────────────────────── */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:1000px){.grid2{grid-template-columns:1fr}}

/* ── Positions ───────────────────────────────────────────────── */
.pos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:10px;padding:14px}
.pos-card{background:var(--panel3);border:1px solid var(--line2);border-radius:var(--radius-sm);
  padding:14px 16px;transition:border-color .25s,transform .15s}
.pos-card:hover{transform:translateY(-2px);border-color:var(--win)}
.pos-card.short:hover{border-color:var(--loss)}
.pos-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.pos-sym{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:14px;color:var(--ink)}
.pos-detail{display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;color:var(--muted)}
.pos-detail .d-item{display:flex;flex-direction:column;gap:2px}
.pos-detail .d-val{color:var(--text);font-weight:500;font-family:'JetBrains Mono',monospace;font-size:11.5px}
.pos-pnl{font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700}
.pos-pnl.pos{color:var(--win)}.pos-pnl.neg{color:var(--loss)}
.pos-sltp{display:flex;gap:7px;margin-top:10px}
.sl-tag,.tp-tag{padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;font-family:'JetBrains Mono',monospace}
.sl-tag{background:var(--loss-dim);color:var(--loss);border:1px solid rgba(255,90,95,.3)}
.tp-tag{background:var(--win-dim);color:var(--win);border:1px solid rgba(62,224,140,.3)}

/* ── Tables ──────────────────────────────────────────────────── */
table{width:100%;border-collapse:collapse}
th{text-align:left;color:var(--muted);font-weight:600;padding:10px 16px;
  text-transform:uppercase;font-size:9px;letter-spacing:.9px;border-bottom:1px solid var(--line)}
td{padding:10px 16px;border-bottom:1px solid var(--line);vertical-align:middle;font-size:12px;transition:background .15s}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.02)}
tr.row-new td{animation:rowGlow 1.8s ease}
.empty{text-align:center;padding:34px;color:var(--faint);font-size:12px}
.pill{display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;
  font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.3px}
.pill.buy,.pill.long{background:var(--win-dim);color:var(--win);border:1px solid rgba(62,224,140,.25)}
.pill.sell,.pill.short{background:var(--loss-dim);color:var(--loss);border:1px solid rgba(255,90,95,.25)}
.pill.hold{background:var(--panel3);color:var(--muted);border:1px solid var(--line2)}
.pnl{font-family:'JetBrains Mono',monospace}.pnl.pos{color:var(--win)}.pnl.neg{color:var(--loss)}
.conf-wrap{display:flex;align-items:center;gap:7px}
.conf-bar{height:4px;border-radius:2px;background:var(--panel3);width:64px;flex-shrink:0}
.conf-fill{height:100%;border-radius:2px;transition:width .5s}
.conf-pct{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;min-width:30px}
.reason-cell{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:11px}
.strat-row{display:flex;align-items:center;gap:10px;padding:10px 16px;border-bottom:1px solid var(--line)}
.strat-row:last-child{border-bottom:none}
.strat-name{font-family:'JetBrains Mono',monospace;font-weight:600;font-size:11px;color:var(--ink);width:90px;flex-shrink:0}
.strat-bar-wrap{flex:1;height:5px;background:var(--panel3);border-radius:3px;overflow:hidden}
.strat-bar-fill{height:100%;border-radius:3px;transition:width .7s}
.strat-meta{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);width:160px;text-align:right;flex-shrink:0}
.ban-row{display:flex;align-items:center;justify-content:space-between;
  padding:9px 16px;border-bottom:1px solid var(--line);font-size:12px}
.ban-row:last-child{border-bottom:none}
.ban-sym{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--loss)}
.ban-timer{color:var(--faint);font-size:10px;font-family:'JetBrains Mono',monospace}
#halt-banner{display:none;margin:14px 22px -4px;padding:12px 18px;border-radius:var(--radius-sm);
  background:rgba(255,90,95,.1);border:1px solid rgba(255,90,95,.35);
  color:var(--loss);font-size:12px;font-weight:600;text-align:center}
#halt-banner.show{display:block}
#toast{position:fixed;bottom:22px;right:22px;background:var(--panel2);border:1px solid var(--line2);
  border-radius:10px;padding:11px 17px;font-size:12px;color:var(--text);
  font-family:'JetBrains Mono',monospace;box-shadow:0 12px 36px #000a;
  opacity:0;transform:translateY(12px);transition:all .3s;z-index:999;pointer-events:none}
#toast.show{opacity:1;transform:translateY(0)}
#footer{font-size:10px;color:var(--faint);padding:4px 22px 22px;text-align:right;font-family:'JetBrains Mono',monospace}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🤖</div>
    <div class="logo-text"><h1>CRYPTOBOT</h1><p>Live Dashboard</p></div>
  </div>
  <div class="header-right">
    <div class="capital-badge"><span>Capital</span><strong id="h-budget">$—</strong></div>
    <div class="status-pill"><div class="dot" id="dot"></div><span id="status-text">Connecting…</span></div>
    <span id="update-time"></span>
  </div>
</header>

<div class="ticker-wrap">
  <div class="ticker-track" id="ticker-track">
    <div class="ti"><span class="ti-sym">Loading…</span></div>
  </div>
</div>

<div id="halt-banner">🛑 Trading Halted — <span id="halt-reason">Daily loss limit</span></div>

<div class="tab-nav">
  <button class="tab-btn active" onclick="switchTab('overview')">📊 Overview</button>
  <button class="tab-btn" onclick="switchTab('positions')">📂 Positions <span class="tab-badge" id="tb-pos">0</span></button>
  <button class="tab-btn" onclick="switchTab('signals')">📡 Signals <span class="tab-badge" id="tb-sig">0</span></button>
  <button class="tab-btn" onclick="switchTab('history')">📜 History <span class="tab-badge" id="tb-hist">0</span></button>
</div>

<!-- OVERVIEW -->
<div id="tab-overview" class="tab-pane active">
<main>
  <div class="cards-row row-6">
    <div class="card capital-card c-signal">
      <div class="c-label">💰 Capital</div>
      <div class="c-value" id="s-budget">—</div>
      <div class="c-sub" id="s-deployed">Total budget USDT</div>
    </div>
    <div class="card c-green">
      <div class="c-label">📈 Total Profit</div>
      <div class="c-value" id="s-tprofit">—</div>
      <div class="c-sub">Gross winning trades</div>
    </div>
    <div class="card c-red">
      <div class="c-label">📉 Total Loss</div>
      <div class="c-value" id="s-tloss">—</div>
      <div class="c-sub">Gross losing trades</div>
    </div>
    <div class="card c-blue">
      <div class="c-label">🎯 Win Rate</div>
      <div class="c-value" id="s-acc">—</div>
      <div class="c-sub" id="s-wl">— / —</div>
    </div>
    <div class="card" id="pnl-card">
      <div class="c-label">⚡ Realised P&amp;L</div>
      <div class="c-value" id="s-pnl">—</div>
      <div class="c-sub">Net USDT closed</div>
    </div>
    <div class="card c-gold">
      <div class="c-label">🔓 Open Positions</div>
      <div class="c-value" id="s-open">—</div>
      <div class="c-sub" id="s-open-sub">active</div>
    </div>
  </div>

  <div class="cards-row row-5">
    <div class="card c-purple">
      <div class="c-label">⚖️ Profit Factor</div>
      <div class="c-value" id="s-pf">—</div>
      <div class="c-sub">≥ 1.5 = good</div>
    </div>
    <div class="card c-green">
      <div class="c-label">✅ Avg Win</div>
      <div class="c-value" id="s-aw">—</div>
      <div class="c-sub">USDT per win</div>
    </div>
    <div class="card c-red">
      <div class="c-label">❌ Avg Loss</div>
      <div class="c-value" id="s-al">—</div>
      <div class="c-sub">USDT per loss</div>
    </div>
    <div class="card c-gold">
      <div class="c-label">🏆 Risk/Reward</div>
      <div class="c-value" id="s-rr">—</div>
      <div class="c-sub">avg win ÷ avg loss</div>
    </div>
    <div class="card" id="daily-card">
      <div class="c-label">🗓️ Daily P&amp;L</div>
      <div class="c-value" id="s-daily">—</div>
      <div class="c-sub">Resets UTC midnight</div>
    </div>
  </div>

  <!-- Live Charts -->
  <div class="panel">
    <div class="panel-hdr">
      <h2>📈 Live Charts — BTC · ETH · SOL</h2>
      <div class="tf-group">
        <button class="tf-btn active" data-tf="15m" onclick="setTf('15m')">15m</button>
        <button class="tf-btn" data-tf="30m" onclick="setTf('30m')">30m</button>
        <button class="tf-btn" data-tf="1h"  onclick="setTf('1h')">1h</button>
      </div>
      <span class="badge live">live</span>
    </div>
    <div class="charts-row">
      <div class="chart-wrap">
        <div class="cw-hdr">
          <div class="cw-left"><span class="cw-sym gold">BTC/USDT</span><span class="cw-price" id="cpx-BTCUSDT">—</span></div>
          <div class="cw-meta"><span class="cw-chg flat" id="cch-BTCUSDT">—</span><span class="cw-vol" id="cvol-BTCUSDT"></span></div>
        </div>
        <div class="chart-loading" id="cload-BTCUSDT">Loading BTC…</div>
        <div class="cw-chart" id="chart-BTCUSDT" style="display:none"></div>
      </div>
      <div class="chart-wrap">
        <div class="cw-hdr">
          <div class="cw-left"><span class="cw-sym blue">ETH/USDT</span><span class="cw-price" id="cpx-ETHUSDT">—</span></div>
          <div class="cw-meta"><span class="cw-chg flat" id="cch-ETHUSDT">—</span><span class="cw-vol" id="cvol-ETHUSDT"></span></div>
        </div>
        <div class="chart-loading" id="cload-ETHUSDT">Loading ETH…</div>
        <div class="cw-chart" id="chart-ETHUSDT" style="display:none"></div>
      </div>
      <div class="chart-wrap">
        <div class="cw-hdr">
          <div class="cw-left"><span class="cw-sym purple">SOL/USDT</span><span class="cw-price" id="cpx-SOLUSDT">—</span></div>
          <div class="cw-meta"><span class="cw-chg flat" id="cch-SOLUSDT">—</span><span class="cw-vol" id="cvol-SOLUSDT"></span></div>
        </div>
        <div class="chart-loading" id="cload-SOLUSDT">Loading SOL…</div>
        <div class="cw-chart" id="chart-SOLUSDT" style="display:none"></div>
      </div>
    </div>
  </div>

  <div class="grid2">
    <div class="panel">
      <div class="panel-hdr"><h2>Strategy Leaderboard</h2><span class="badge">Live</span></div>
      <div id="strat-body"><div class="empty">No strategy data yet</div></div>
    </div>
    <div class="panel">
      <div class="panel-hdr"><h2>Blacklisted Coins</h2><span class="badge" id="ban-count">0</span></div>
      <div id="blacklist-body"><div class="empty">✅ No coins blacklisted</div></div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-hdr"><h2>Per-Coin Performance</h2><span class="badge" id="coin-count">0</span></div>
    <table>
      <thead><tr><th>Coin</th><th>Trades</th><th>Win Rate</th><th>P&amp;L</th><th>Status</th></tr></thead>
      <tbody id="coin-body"><tr><td colspan="5" class="empty">No data</td></tr></tbody>
    </table>
  </div>
</main>
</div>

<!-- POSITIONS -->
<div id="tab-positions" class="tab-pane">
<main>
  <div class="panel">
    <div class="panel-hdr"><h2>Open Positions</h2><span class="badge" id="pos-count">0</span></div>
    <div class="pos-grid" id="positions-list"><div class="empty">No open positions</div></div>
  </div>
</main>
</div>

<!-- SIGNALS -->
<div id="tab-signals" class="tab-pane">
<main>
  <div class="panel">
    <div class="panel-hdr"><h2>Recent Signals</h2><span class="badge" id="sig-count">0</span></div>
    <table>
      <thead><tr><th>Symbol</th><th>Action</th><th>Price</th><th>Confidence</th><th>Reasoning</th></tr></thead>
      <tbody id="signals-body"><tr><td colspan="5" class="empty">Waiting…</td></tr></tbody>
    </table>
  </div>
</main>
</div>

<!-- HISTORY -->
<div id="tab-history" class="tab-pane">
<main>
  <div class="panel">
    <div class="panel-hdr"><h2>Trade History</h2><span class="badge" id="hist-count">0</span></div>
    <table>
      <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reason</th></tr></thead>
      <tbody id="history-body"><tr><td colspan="6" class="empty">No closed trades yet</td></tr></tbody>
    </table>
  </div>
</main>
</div>

<div id="footer">Last refreshed: <span id="last-update">—</span></div>
<div id="toast"></div>

<script>
// ── Candlestick Charts ────────────────────────────────────────
const CHART_SYMS=['BTCUSDT','ETHUSDT','SOLUSDT'];
const SYM_COLS={BTCUSDT:'#f0b429',ETHUSDT:'#58a6ff',SOLUSDT:'#bc8cff'};
const BINANCE='https://testnet.binance.vision/api/v3/klines';
let currentTf='15m',lwCharts={},cSeries={},vSeries={},entryLines={},chartsReady=false;
const LWC=window.LightweightCharts;

function chartOpts(w){return{width:w,height:300,
  layout:{background:{type:'solid',color:'#121920'},textColor:'#607080',fontFamily:"'JetBrains Mono',monospace",fontSize:10},
  grid:{vertLines:{color:'#1c2430',style:1},horzLines:{color:'#1c2430',style:1}},
  crosshair:{mode:LWC.CrosshairMode.Normal,
    vertLine:{color:'#475260',width:1,style:3,labelBackgroundColor:'#18212a'},
    horzLine:{color:'#475260',width:1,style:3,labelBackgroundColor:'#18212a'}},
  rightPriceScale:{borderColor:'#1c2430',scaleMargins:{top:.12,bottom:.22}},
  timeScale:{borderColor:'#1c2430',timeVisible:true,secondsVisible:false,rightOffset:8,barSpacing:8}
};}

function initCharts(){
  if(!LWC||chartsReady)return;
  CHART_SYMS.forEach(sym=>{
    const cont=document.getElementById('chart-'+sym);if(!cont)return;
    cont.style.display='block';
    const ch=LWC.createChart(cont,chartOpts(cont.parentElement.clientWidth||400));
    const cs=ch.addCandlestickSeries({upColor:'#3ee08c',downColor:'#ff5a5f',borderUpColor:'#3ee08c',borderDownColor:'#ff5a5f',wickUpColor:'#3ee08c',wickDownColor:'#ff5a5f'});
    const vs=ch.addHistogramSeries({color:SYM_COLS[sym]+'33',priceFormat:{type:'volume'},priceScaleId:'vol'});
    ch.priceScale('vol').applyOptions({scaleMargins:{top:.84,bottom:0}});
    lwCharts[sym]=ch;cSeries[sym]=cs;vSeries[sym]=vs;
    const ro=new ResizeObserver(e=>{for(const en of e)if(lwCharts[sym])lwCharts[sym].applyOptions({width:en.contentRect.width});});
    ro.observe(cont);
  });
  chartsReady=true;
}

async function loadChart(sym,tf){
  const lo=document.getElementById('cload-'+sym),ce=document.getElementById('chart-'+sym);
  if(lo){lo.style.display='flex';lo.style.color='var(--muted)';lo.innerHTML='<span>Loading '+sym.replace('USDT','')+'…</span>';lo.style.animationName='';}
  if(ce)ce.style.display='none';
  try{
    const r=await fetch(`${BINANCE}?symbol=${sym}&interval=${tf}&limit=200`);
    if(!r.ok)throw new Error('HTTP '+r.status);
    const raw=await r.json();
    const candles=raw.map(k=>({time:Math.floor(k[0]/1000),open:+k[1],high:+k[2],low:+k[3],close:+k[4]}));
    const volumes=raw.map(k=>({time:Math.floor(k[0]/1000),value:+k[5],color:+k[4]>=+k[1]?'rgba(62,224,140,.25)':'rgba(255,90,95,.2)'}));
    if(!cSeries[sym])return;
    cSeries[sym].setData(candles);vSeries[sym].setData(volumes);
    lwCharts[sym].timeScale().fitContent();
    if(lo)lo.style.display='none';if(ce)ce.style.display='block';
    const last=candles[candles.length-1],chg=((last.close-candles[0].open)/candles[0].open*100);
    const vol24=raw.slice(-96).reduce((a,k)=>a+(+k[5]),0);
    const pe=document.getElementById('cpx-'+sym),ce2=document.getElementById('cch-'+sym),ve=document.getElementById('cvol-'+sym);
    if(pe)pe.textContent=fmtPx(last.close);
    if(ce2){ce2.textContent=(chg>=0?'+':'')+chg.toFixed(2)+'%';ce2.className='cw-chg '+(chg>0?'pos':chg<0?'neg':'flat');}
    if(ve)ve.textContent='Vol: '+fmtVol(vol24);
  }catch(e){
    if(lo){lo.style.display='flex';lo.style.color='var(--loss)';lo.style.animationName='none';lo.innerHTML='⚠️ '+sym.replace('USDT','')+' unavailable';}
  }
}

async function updateLastCandle(sym){
  if(!cSeries[sym])return;
  try{
    const r=await fetch(`${BINANCE}?symbol=${sym}&interval=${currentTf}&limit=2`);
    if(!r.ok)return;
    const raw=await r.json(),k=raw[raw.length-1];
    cSeries[sym].update({time:Math.floor(k[0]/1000),open:+k[1],high:+k[2],low:+k[3],close:+k[4]});
    vSeries[sym].update({time:Math.floor(k[0]/1000),value:+k[5],color:+k[4]>=+k[1]?'rgba(62,224,140,.25)':'rgba(255,90,95,.2)'});
    const pe=document.getElementById('cpx-'+sym);if(pe)pe.textContent=fmtPx(+k[4]);
  }catch{}
}

function setEntryLine(sym,ep){
  if(!cSeries[sym]||!ep)return;
  if(entryLines[sym]){try{cSeries[sym].removePriceLine(entryLines[sym]);}catch{}}
  entryLines[sym]=cSeries[sym].createPriceLine({price:ep,color:'#f0b429',lineWidth:1,lineStyle:LWC.LineStyle.Dashed,axisLabelVisible:true,title:'Entry'});
}

function setTf(tf){
  currentTf=tf;
  document.querySelectorAll('.tf-btn').forEach(b=>b.classList.toggle('active',b.dataset.tf===tf));
  CHART_SYMS.forEach(sym=>loadChart(sym,tf));
}

// ── Utils ────────────────────────────────────────────────────
let prevPrices={},prevStats={},firstLoad=true,prevHistIds={sig:null,hist:null};
const $=id=>document.getElementById(id);
function fmt(n,dp=2){if(n==null)return'—';const v=Number(n);return isNaN(v)?'—':v.toLocaleString('en-US',{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function fmtPx(p){if(p==null)return'—';const v=Number(p);if(isNaN(v))return'—';return v>=1000?'$'+fmt(v,2):v>=1?'$'+fmt(v,3):'$'+fmt(v,4)}
function fmtVol(v){return v>=1e9?(v/1e9).toFixed(2)+'B':v>=1e6?(v/1e6).toFixed(2)+'M':v>=1e3?(v/1e3).toFixed(1)+'K':v.toFixed(0)}
function confCol(c){return c>=75?'var(--win)':c>=55?'var(--gold)':'var(--muted)'}
function toast(msg,ms=2800){const t=$('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),ms)}
function tween(el,to,fmt2){
  if(!el||el._tTo===to)return;
  const from=typeof el._tV==='number'?el._tV:to;
  el._tTo=to;const s=performance.now(),d=500;
  const step=n=>{const p=Math.min((n-s)/d,1),e=1-Math.pow(1-p,3),v=from+(to-from)*e;
    el._tV=v;el.textContent=fmt2(v);if(p<1)requestAnimationFrame(step);else{el._tV=to;el.textContent=fmt2(to);}};
  requestAnimationFrame(step);}

function switchTab(name){
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  $('tab-'+name).classList.add('active');
  document.querySelector(`[onclick="switchTab('${name}')"]`).classList.add('active');
}

function buildTicker(prices){
  const entries=Object.entries(prices);if(!entries.length)return;
  const html=entries.map(([sym,px])=>{
    const prev=prevPrices[sym],dir=!prev?'':(px>prev?'up':px<prev?'dn':'');
    const arrow=!prev?'–':(px>prev?'▲':px<prev?'▼':'–');
    const col=dir==='up'?'var(--win)':dir==='dn'?'var(--loss)':'var(--faint)';
    return`<div class="ti ${dir==='up'?'flash-up':dir==='dn'?'flash-dn':''}"><span class="ti-sym">${sym}</span><span class="ti-px">${fmtPx(px)}</span><span class="ti-arr" style="color:${col}">${arrow}</span></div>`;
  }).join('');
  $('ticker-track').innerHTML=html+html;
}

function update(data){
  const online=data.bot_online;
  $('dot').className='dot'+(online?' online':'');
  $('status-text').textContent=online?'Bot online':'Bot offline';
  if(data.last_updated){const d=new Date(data.last_updated);$('update-time').textContent='Updated '+d.toLocaleTimeString();}
  const halted=data.trading_halted||false;
  if(halted){$('halt-banner').classList.add('show');$('halt-reason').textContent=data.halt_reason||'Daily loss limit';}
  else $('halt-banner').classList.remove('show');
  if(data.prices&&Object.keys(data.prices).length){buildTicker(data.prices);prevPrices={...data.prices};}

  const positions=data.positions||[];
  CHART_SYMS.forEach(sym=>{const pos=positions.find(p=>p.symbol===sym);if(pos&&pos.entry&&chartsReady)setEntryLine(sym,pos.entry);});

  const budget=data.budget||0;
  $('h-budget').textContent=budget>0?'$'+fmt(budget,0):'—';
  $('s-budget').textContent=budget>0?'$'+fmt(budget,0):'—';
  const deployed=positions.reduce((a,p)=>p.entry&&p.quantity?a+p.entry*p.quantity:a,0);
  $('s-deployed').textContent=deployed>0?`$${fmt(deployed,2)} deployed · $${fmt(budget-deployed,2)} free`:'Total budget USDT';

  const hist=data.trade_history||[];
  const tProfit=hist.reduce((a,t)=>(t.pnl||0)>0?a+(t.pnl||0):a,0);
  const tLoss=Math.abs(hist.reduce((a,t)=>(t.pnl||0)<0?a+(t.pnl||0):a,0));
  $('s-tprofit').textContent=tProfit>0?'+'+fmt(tProfit,4):'—';
  $('s-tloss').textContent=tLoss>0?'-'+fmt(tLoss,4):'—';

  const s=data.stats||{},pnl=s.realized_pnl??0;
  tween($('s-acc'),s.accuracy_pct??0,v=>v.toFixed(1)+'%');
  $('s-wl').textContent=`${s.wins??0} wins / ${s.losses??0} losses`;
  tween($('s-open'),s.open_positions??0,v=>Math.round(v).toString());
  $('s-open-sub').textContent=`${s.open_longs??0}L / ${s.open_shorts??0}S`;
  const pe=$('s-pnl'),pc=$('pnl-card');
  tween(pe,pnl,v=>(v>=0?'+':'')+fmt(v,4));
  pe.style.color=pnl>=0?'var(--win)':'var(--loss)';
  pc.className='card '+(pnl>=0?'c-green':'c-red');
  if(!firstLoad&&prevStats.realized_pnl!==undefined&&pnl!==prevStats.realized_pnl){
    const diff=pnl-prevStats.realized_pnl;toast((diff>=0?'📈 P&L +':'📉 P&L ')+fmt(diff,4)+' USDT');}
  prevStats={...s};

  const daily=data.daily_pnl??0;
  tween($('s-daily'),daily,v=>(v>=0?'+':'')+fmt(v,4));
  $('s-daily').style.color=daily>=0?'var(--win)':'var(--loss)';
  $('daily-card').className='card '+(daily>=0?'c-green':'c-red');

  const pf=s.profit_factor??0,aw=s.avg_win??0,al=s.avg_loss??0,rr=al>0?Math.round(aw/al*100)/100:0;
  tween($('s-pf'),pf,v=>v>0?v.toFixed(2):'—');
  $('s-pf').style.color=pf>=1.5?'var(--win)':pf>=1?'var(--gold)':'var(--loss)';
  tween($('s-aw'),aw,v=>v>0?'+'+fmt(v,4):'—');
  tween($('s-al'),al,v=>v>0?'-'+fmt(v,4):'—');
  tween($('s-rr'),rr,v=>v>0?v.toFixed(2)+'x':'—');

  $('tb-pos').textContent=positions.length;$('tb-pos').className='tab-badge'+(positions.length?' green':'');
  const sigs=data.signals||[];$('tb-sig').textContent=sigs.length;
  $('tb-hist').textContent=hist.length;$('tb-hist').className='tab-badge'+(hist.length?' green':'');

  // Positions
  $('pos-count').textContent=positions.length;
  const pl=$('positions-list');
  if(!positions.length){pl.innerHTML='<div class="empty">No open positions</div>';}
  else{pl.innerHTML=positions.map(p=>{
    const isShort=p.side==='SHORT',cur=(data.prices||{})[p.symbol]||p.entry;
    const unreal=isShort?(p.entry-cur)*p.quantity:(cur-p.entry)*p.quantity;
    const cls=unreal>=0?'pos':'neg',sign=unreal>=0?'+':'';
    const sl=isShort?p.entry*(1+((p.stop_loss_pct||1.5)/100)):p.entry*(1-((p.stop_loss_pct||1.5)/100));
    const tp=isShort?p.entry*(1-((p.take_profit_pct||3)/100)):p.entry*(1+((p.take_profit_pct||3)/100));
    return`<div class="pos-card${isShort?' short':''}">
      <div class="pos-hdr"><span class="pos-sym">${p.symbol}</span><span class="pos-pnl ${cls}">${sign}${fmt(unreal,4)}</span></div>
      <div class="pos-detail">
        <div class="d-item">Entry<div class="d-val">${fmtPx(p.entry)}</div></div>
        <div class="d-item">Current<div class="d-val">${fmtPx(cur)}</div></div>
        <div class="d-item">Qty<div class="d-val">${p.quantity}</div></div>
        <div class="d-item">Side<div class="d-val"><span class="pill ${isShort?'short':'long'}">${p.side||'LONG'}</span></div></div>
      </div>
      <div class="pos-sltp"><span class="sl-tag">SL ${fmtPx(sl)}</span><span class="tp-tag">TP ${fmtPx(tp)}</span></div>
    </div>`;
  }).join('');}

  // Signals
  $('sig-count').textContent=sigs.length;
  const sigsRev=[...sigs].reverse(),sb=$('signals-body');
  if(!sigsRev.length){sb.innerHTML='<tr><td colspan="5" class="empty">Waiting…</td></tr>';}
  else{sb.innerHTML=sigsRev.slice(0,30).map((s2,i)=>{
    const ac=(s2.action||'HOLD').toLowerCase(),c2=s2.confidence||0,col=confCol(c2);
    const bar=`<div class="conf-wrap"><div class="conf-bar"><div class="conf-fill" style="width:${c2}%;background:${col}"></div></div><span class="conf-pct" style="color:${col}">${c2}%</span></div>`;
    const rea=(s2.reasoning||'').replace(/"/g,'&quot;');
    const isNew=i===0&&!firstLoad&&JSON.stringify(s2)!==prevHistIds.sig;
    return`<tr${isNew?' class="row-new"':''}><td><strong style="color:var(--ink)">${s2.symbol}</strong></td>
      <td><span class="pill ${ac}">${s2.action}</span></td>
      <td class="mono">${fmtPx(s2.entry)}</td><td>${bar}</td>
      <td class="reason-cell" title="${rea}">${s2.reasoning||'—'}</td></tr>`;
  }).join('');prevHistIds.sig=JSON.stringify(sigsRev[0]);}

  // History
  const histRev=[...hist].reverse();
  $('hist-count').textContent=histRev.length;
  const hb=$('history-body');
  if(!histRev.length){hb.innerHTML='<tr><td colspan="6" class="empty">No closed trades yet</td></tr>';}
  else{hb.innerHTML=histRev.slice(0,200).map((t,i)=>{
    const p2=t.pnl??0,cls2=p2>=0?'pos':'neg',sign2=p2>=0?'+':'',icon=p2>=0?'✅':'❌';
    const isNew=i===0&&!firstLoad&&JSON.stringify(t)!==prevHistIds.hist;
    const rea=(t.reasoning||'').replace(/"/g,'&quot;');
    return`<tr${isNew?' class="row-new"':''}><td><strong style="color:var(--ink)">${t.symbol}</strong></td>
      <td><span class="pill ${(t.side||'').toLowerCase()}">${t.side||'—'}</span></td>
      <td class="mono">${fmtPx(t.entry)}</td><td class="mono">${t.exit?fmtPx(t.exit):'—'}</td>
      <td class="pnl ${cls2}">${icon} ${sign2}${fmt(p2,4)}</td>
      <td class="reason-cell" title="${rea}">${t.reasoning||'—'}</td></tr>`;
  }).join('');prevHistIds.hist=JSON.stringify(histRev[0]);}

  // Strategy
  const strats=data.strategy_stats||{},sb2=$('strat-body');
  if(!Object.keys(strats).length){sb2.innerHTML='<div class="empty">No strategy data yet</div>';}
  else{sb2.innerHTML=Object.keys(strats).sort((a,b)=>{
    return(strats[b].wins/(strats[b].wins+strats[b].losses||1))-(strats[a].wins/(strats[a].wins+strats[a].losses||1));
  }).map(k=>{
    const st=strats[k],tot=st.wins+st.losses,wr=tot>0?Math.round(st.wins/tot*100):0;
    const col=wr>=55?'var(--win)':wr>=45?'var(--gold)':'var(--loss)';
    return`<div class="strat-row"><span class="strat-name">${k}</span>
      <div class="strat-bar-wrap"><div class="strat-bar-fill" style="width:${wr}%;background:${col}"></div></div>
      <span class="strat-meta" style="color:${col}">${tot}t · ${wr}% · ${st.pnl>=0?'+':''}${fmt(st.pnl,4)}</span></div>`;
  }).join('');}

  // Blacklist
  const bans=data.blacklisted_coins||{},banKeys=Object.keys(bans);
  $('ban-count').textContent=banKeys.length;
  const blb=$('blacklist-body');
  if(!banKeys.length){blb.innerHTML='<div class="empty">✅ No coins blacklisted</div>';}
  else{blb.innerHTML=banKeys.map(sym=>{
    const hrs=Math.max(0,(bans[sym]*1000-Date.now())/3600000).toFixed(1);
    return`<div class="ban-row"><span class="ban-sym">⛔ ${sym}</span><span class="ban-timer">${hrs}h left</span></div>`;
  }).join('');}

  // Per-coin
  const cs2=s.coin_stats||{},ck=Object.keys(cs2).sort((a,b)=>(cs2[a].pnl||0)-(cs2[b].pnl||0));
  $('coin-count').textContent=ck.length;
  const cb=$('coin-body');
  if(!ck.length){cb.innerHTML='<tr><td colspan="5" class="empty">No data</td></tr>';}
  else{cb.innerHTML=ck.map(sym=>{
    const c3=cs2[sym],tot=c3.wins+c3.losses,wr=tot>0?Math.round(c3.wins/tot*100):0;
    const col=wr>=55?'var(--win)':wr>=40?'var(--gold)':'var(--loss)';
    const isBanned=banKeys.includes(sym),warn=!isBanned&&tot>=3&&wr<40;
    const status=isBanned?'<span class="pill sell">BANNED</span>':warn?'<span class="pill sell">⚠️ Watch</span>':'<span class="pill hold">Active</span>';
    return`<tr><td><strong style="color:var(--ink)">${sym}</strong></td><td class="mono">${tot}</td>
      <td><span class="mono" style="color:${col};font-weight:600">${wr}%</span>
        <div style="margin-top:3px;height:3px;width:${wr}px;max-width:100px;background:${col};border-radius:2px"></div></td>
      <td class="pnl ${c3.pnl>=0?'pos':'neg'}">${c3.pnl>=0?'+':''}${fmt(c3.pnl,4)}</td><td>${status}</td></tr>`;
  }).join('');}

  $('last-update').textContent=new Date().toLocaleTimeString();
  firstLoad=false;
}

async function poll(){
  try{const r=await fetch('/api/all');if(r.ok)update(await r.json());else throw 0;}
  catch{$('status-text').textContent='Disconnected';$('dot').className='dot';}
}

window.addEventListener('DOMContentLoaded',()=>{
  initCharts();
  CHART_SYMS.forEach(s=>loadChart(s,currentTf));
  poll();
  setInterval(poll,5000);
  setInterval(()=>CHART_SYMS.forEach(s=>updateLastCandle(s)),30000);
});
window.addEventListener('resize',()=>{
  CHART_SYMS.forEach(sym=>{const el=document.getElementById('chart-'+sym);
    if(el&&lwCharts[sym])lwCharts[sym].applyOptions({width:el.clientWidth});});
});
</script>
</body>
</html>"""

@app.route("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.route("/api/all")
def api_all():
    fresh = _read_bot_state()
    if fresh:
        with state_lock:
            state["stats"]         = fresh.get("stats",         state["stats"])
            state["positions"]     = fresh.get("positions",     state["positions"])
            state["signals"]       = fresh.get("signals",       state["signals"])
            state["trade_history"] = fresh.get("trade_history", state["trade_history"])
            state["daily_pnl"]     = fresh.get("daily_pnl",     0.0)
            if fresh.get("prices") and not state["prices"]:
                state["prices"] = fresh["prices"]
            state["bot_online"]    = fresh.get("bot_online", True)
            state["last_updated"]  = datetime.now(timezone.utc).isoformat()
    with state_lock:
        th = state["trade_history"]
        return jsonify({
            "stats":             state["stats"],
            "positions":         state["positions"],
            "prices":            state["prices"],
            "signals":           state["signals"][-30:],
            "trade_history":     th[-200:],
            "strategy_stats":    fresh.get("strategy_stats",    {}) if fresh else {},
            "blacklisted_coins": fresh.get("blacklisted_coins", {}) if fresh else {},
            "last_updated":      state["last_updated"],
            "bot_online":        state["bot_online"],
            "daily_pnl":         state["daily_pnl"],
            "trading_halted":    fresh.get("trading_halted", False) if fresh else False,
            "halt_reason":       fresh.get("halt_reason", "")       if fresh else "",
            "budget":            BUDGET,
        })

@app.route("/api/stats")
def api_stats():
    with state_lock: return jsonify(state["stats"])
@app.route("/api/positions")
def api_positions():
    with state_lock: return jsonify(state["positions"])
@app.route("/api/prices")
def api_prices():
    with state_lock: return jsonify(state["prices"])
@app.route("/api/signals")
def api_signals():
    with state_lock: return jsonify(state["signals"])
@app.route("/api/history")
def api_history():
    with state_lock: return jsonify(state["trade_history"])

def poll_loop():
    import aiohttp
    async def fetch():
        BASE="https://testnet.binance.vision"
        syms=os.environ.get("SYMBOLS","BTCUSDT,ETHUSDT,SOLUSDT").split(",")
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    prices={}
                    for s in syms:
                        async with session.get(f"{BASE}/api/v3/ticker/price?symbol={s}",timeout=aiohttp.ClientTimeout(total=5)) as r:
                            if r.status==200: prices[s]=float((await r.json())["price"])
                    bs=_read_bot_state()
                    with state_lock:
                        if prices: state["prices"]=prices
                        state["last_updated"]=datetime.now(timezone.utc).isoformat()
                        state["bot_online"]=bool(bs)
                        if bs:
                            state["stats"]        =bs.get("stats",        state["stats"])
                            state["positions"]    =bs.get("positions",    [])
                            state["signals"]      =bs.get("signals",      [])
                            state["trade_history"]=bs.get("trade_history",[])
                            state["daily_pnl"]    =bs.get("daily_pnl",   0.0)
                except Exception as e:
                    log.warning(f"Poll: {e}")
                    with state_lock: state["bot_online"]=False
                await asyncio.sleep(10)
    asyncio.run(fetch())

def _read_bot_state():
    try:
        with open("bot_state.json") as f: return json.load(f)
    except: return {}

threading.Thread(target=poll_loop, daemon=True).start()

if __name__=="__main__":
    print("="*55)
    print(f"  📊 CryptoBot Dashboard  →  http://localhost:5000")
    print(f"  💰 Budget: ${BUDGET:,.0f} USDT")
    print("="*55)
    app.run(host="0.0.0.0", port=5000, debug=False)
