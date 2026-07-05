"""
Dashboard Server — Final Polish
Run alongside bot.py:  python dashboard.py
Visit:  http://localhost:5000
"""

import json, os, time, threading, asyncio, logging
from datetime import datetime, timezone
from flask import Flask, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app  = Flask(__name__)
CORS(app)

state = {
    "stats":        {"total_trades":0,"wins":0,"losses":0,
                     "realized_pnl":0.0,"accuracy_pct":0,"open_positions":0},
    "positions":    [],
    "prices":       {},
    "signals":      [],
    "trade_history":[],
    "last_updated": None,
    "bot_online":   False,
}
state_lock = threading.Lock()

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoBot — Live Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080c10;--bg1:#0d1117;--bg2:#141b22;--bg3:#1c2430;
  --border:#21262d;--border2:#30363d;
  --green:#39d98a;--green-dim:#1a3a2a;--green-glow:rgba(57,217,138,.2);
  --red:#f85149;--red-dim:#3a1a1a;--red-glow:rgba(248,81,73,.15);
  --gold:#e3b341;--blue:#58a6ff;--purple:#bc8cff;--muted:#8b949e;
  --text:#c9d1d9;--white:#f0f6fc;
  --font:'Inter',system-ui,sans-serif;
}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;font-size:13px}
header{display:flex;align-items:center;justify-content:space-between;
       padding:12px 20px;background:var(--bg1);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:34px;height:34px;background:linear-gradient(135deg,#39d98a,#1a8a55);
           border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 0 16px var(--green-glow)}
.logo-text h1{font-size:14px;font-weight:700;letter-spacing:.4px;color:var(--white)}
.logo-text p{font-size:10px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase}
.status-bar{display:flex;align-items:center;gap:12px}
.status{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);
        background:var(--bg2);padding:5px 12px;border-radius:20px;border:1px solid var(--border)}
.dot{width:7px;height:7px;border-radius:50%;background:#444;transition:all .3s}
.dot.online{background:var(--green);box-shadow:0 0 8px var(--green)}
#update-time{font-size:11px;color:var(--muted)}
.prices-bar{display:flex;gap:8px;padding:10px 20px;background:var(--bg1);
            border-bottom:1px solid var(--border);flex-wrap:wrap;overflow-x:auto}
.price-chip{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
            padding:5px 12px;font-size:12px;font-weight:600;cursor:default;
            transition:border-color .3s,transform .15s;white-space:nowrap}
.price-chip:hover{transform:translateY(-1px)}
.price-chip .sym{color:var(--muted);font-weight:400;font-size:10px;margin-right:5px;letter-spacing:.5px}
.price-chip.up{border-color:#1e4d35;color:var(--green)}
.price-chip.dn{border-color:#4d1e1e;color:var(--red)}
.price-chip .chg{font-size:10px;margin-left:4px;opacity:.7}
main{padding:16px 20px;display:grid;gap:14px;max-width:1600px;margin:0 auto}
/* Stats rows */
.stats-row{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.stats-row2{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media(max-width:1100px){.stats-row,.stats-row2{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.stats-row,.stats-row2{grid-template-columns:repeat(2,1fr)}}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
           padding:14px 16px;position:relative;overflow:hidden;transition:border-color .3s}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--border)}
.stat-card.green::before{background:linear-gradient(90deg,var(--green),transparent)}
.stat-card.red::before{background:linear-gradient(90deg,var(--red),transparent)}
.stat-card.blue::before{background:linear-gradient(90deg,var(--blue),transparent)}
.stat-card.gold::before{background:linear-gradient(90deg,var(--gold),transparent)}
.stat-card.purple::before{background:linear-gradient(90deg,var(--purple),transparent)}
.stat-card .label{font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);margin-bottom:10px}
.stat-card .value{font-size:28px;font-weight:700;color:var(--white);line-height:1;letter-spacing:-1px}
.stat-card .sub{font-size:10px;color:var(--muted);margin-top:6px}
.stat-card.green .value{color:var(--green)}
.stat-card.red .value{color:var(--red)}
.stat-card.blue .value{color:var(--blue)}
.stat-card.gold .value{color:var(--gold)}
.stat-card.purple .value{color:var(--purple)}
/* Panel */
.panel{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:0;overflow:hidden}
.panel-header{display:flex;align-items:center;justify-content:space-between;
              padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bg3)}
.panel-header h2{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);font-weight:600}
.badge{background:var(--bg);border:1px solid var(--border2);border-radius:20px;
       padding:1px 8px;font-size:10px;color:var(--muted);font-weight:600}
.badge.red{border-color:#f8514966;color:var(--red)}
/* Positions */
.pos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;padding:14px}
.pos-card{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;
          padding:12px 14px;transition:border-color .3s}
.pos-card:hover{border-color:var(--green)}
.pos-card.short:hover{border-color:var(--red)}
.pos-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.pos-sym{font-weight:700;font-size:14px;color:var(--white)}
.pos-detail{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:var(--muted)}
.pos-detail span{display:flex;flex-direction:column;gap:1px}
.pos-detail .val{color:var(--text);font-weight:500}
.pos-pnl{font-size:16px;font-weight:700;text-align:right}
.pos-pnl.pos{color:var(--green)}.pos-pnl.neg{color:var(--red)}
.pos-sl-tp{display:flex;gap:8px;margin-top:8px;font-size:10px}
.sl-tag,.tp-tag{padding:2px 7px;border-radius:4px;font-weight:600}
.sl-tag{background:var(--red-dim);color:var(--red);border:1px solid #f8514940}
.tp-tag{background:var(--green-dim);color:var(--green);border:1px solid #39d98a40}
/* Tables */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:1000px){.grid2,.grid3{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse}
th{text-align:left;color:var(--muted);font-weight:500;padding:10px 14px;
   text-transform:uppercase;font-size:9px;letter-spacing:.8px;border-bottom:1px solid var(--border)}
td{padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:middle;transition:background .15s}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg3)}
.pill{display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;
      font-size:10px;font-weight:700;letter-spacing:.3px}
.pill.buy,.pill.long{background:var(--green-dim);color:var(--green);border:1px solid #39d98a33}
.pill.sell,.pill.short{background:var(--red-dim);color:var(--red);border:1px solid #f8514933}
.pill.hold{background:#1c2430;color:var(--muted);border:1px solid var(--border)}
.pill.cover{background:#2a1f3d;color:var(--purple);border:1px solid #bc8cff33}
.conf-wrap{display:flex;align-items:center;gap:6px}
.conf-bar{height:4px;border-radius:2px;background:var(--bg3);width:60px;flex-shrink:0}
.conf-fill{height:100%;border-radius:2px;transition:width .5s}
.conf-pct{font-size:11px;font-weight:600;min-width:28px}
.pnl.pos{color:var(--green)}.pnl.neg{color:var(--red)}
.empty{color:var(--muted);font-size:12px;padding:32px;text-align:center;opacity:.6}
td[title]{cursor:help}
.reason-cell{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
             color:var(--muted);font-size:11px}
/* Strategy bars */
.strat-row{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border)}
.strat-row:last-child{border-bottom:none}
.strat-name{font-weight:600;font-size:12px;color:var(--white);width:90px;flex-shrink:0}
.strat-bar-wrap{flex:1;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden}
.strat-bar-fill{height:100%;border-radius:3px;transition:width .6s}
.strat-meta{font-size:10px;color:var(--muted);width:130px;text-align:right;flex-shrink:0}
/* Blacklist */
.ban-row{display:flex;align-items:center;justify-content:space-between;
         padding:8px 14px;border-bottom:1px solid var(--border);font-size:12px}
.ban-row:last-child{border-bottom:none}
.ban-sym{font-weight:700;color:var(--red)}
.ban-timer{color:var(--muted);font-size:10px}
/* Coin stats */
.coin-wr-bar{height:4px;border-radius:2px;display:inline-block;vertical-align:middle;margin-left:6px}
#footer{font-size:10px;color:#3d444d;padding:8px 20px 20px;text-align:right}
#toast{position:fixed;bottom:20px;right:20px;background:var(--bg3);border:1px solid var(--border2);
       border-radius:10px;padding:10px 16px;font-size:12px;color:var(--text);
       box-shadow:0 8px 32px #000a;opacity:0;transform:translateY(10px);
       transition:all .3s;z-index:999;pointer-events:none}
#toast.show{opacity:1;transform:translateY(0)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🤖</div>
    <div class="logo-text">
      <h1>CRYPTOBOT</h1>
      <p>Live Dashboard</p>
    </div>
  </div>
  <div class="status-bar">
    <div class="status">
      <div class="dot" id="dot"></div>
      <span id="status-text">Connecting…</span>
    </div>
    <span id="update-time"></span>
  </div>
</header>

<div class="prices-bar" id="prices-bar">
  <div class="price-chip"><span class="sym">Loading…</span></div>
</div>

<main>
  <!-- Row 1: Core stats -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="label">Total Trades</div>
      <div class="value" id="s-total">—</div>
      <div class="sub">executed</div>
    </div>
    <div class="stat-card green">
      <div class="label">Wins</div>
      <div class="value" id="s-wins">—</div>
      <div class="sub">profitable closes</div>
    </div>
    <div class="stat-card red">
      <div class="label">Losses</div>
      <div class="value" id="s-losses">—</div>
      <div class="sub">losing closes</div>
    </div>
    <div class="stat-card blue">
      <div class="label">Accuracy</div>
      <div class="value" id="s-acc">—</div>
      <div class="sub">win rate</div>
    </div>
    <div class="stat-card" id="pnl-card">
      <div class="label">Realised P&L</div>
      <div class="value" id="s-pnl">—</div>
      <div class="sub">USDT</div>
    </div>
    <div class="stat-card gold">
      <div class="label">Open Positions</div>
      <div class="value" id="s-open">—</div>
      <div class="sub" id="s-open-sub">active</div>
    </div>
  </div>

  <!-- Row 2: Performance stats -->
  <div class="stats-row2">
    <div class="stat-card purple">
      <div class="label">Profit Factor</div>
      <div class="value" id="s-pf">—</div>
      <div class="sub">gross W / gross L (>1.5 = good)</div>
    </div>
    <div class="stat-card green">
      <div class="label">Avg Win</div>
      <div class="value" id="s-aw">—</div>
      <div class="sub">USDT per winning trade</div>
    </div>
    <div class="stat-card red">
      <div class="label">Avg Loss</div>
      <div class="value" id="s-al">—</div>
      <div class="sub">USDT per losing trade</div>
    </div>
    <div class="stat-card gold">
      <div class="label">Risk/Reward</div>
      <div class="value" id="s-rr">—</div>
      <div class="sub">avg win ÷ avg loss</div>
    </div>
  </div>

  <!-- Open Positions -->
  <div class="panel">
    <div class="panel-header">
      <h2>Open Positions</h2>
      <span class="badge" id="pos-count">0</span>
    </div>
    <div class="pos-grid" id="positions-list">
      <div class="empty">No open positions</div>
    </div>
  </div>

  <!-- Strategy Leaderboard + Blacklist -->
  <div class="grid2">
    <div class="panel">
      <div class="panel-header">
        <h2>Strategy Leaderboard</h2>
        <span class="badge">Live</span>
      </div>
      <div id="strat-body"><div class="empty">No strategy data yet</div></div>
    </div>
    <div class="panel">
      <div class="panel-header">
        <h2>Blacklisted Coins</h2>
        <span class="badge red" id="ban-count">0</span>
      </div>
      <div id="blacklist-body"><div class="empty">No coins blacklisted</div></div>
    </div>
  </div>

  <!-- Per-coin breakdown -->
  <div class="panel">
    <div class="panel-header">
      <h2>Per-Coin Performance</h2>
      <span class="badge" id="coin-count">0</span>
    </div>
    <table>
      <thead>
        <tr><th>Coin</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>Status</th></tr>
      </thead>
      <tbody id="coin-body">
        <tr><td colspan="5" class="empty">No trade data yet</td></tr>
      </tbody>
    </table>
  </div>

  <!-- Signals + History -->
  <div class="grid2">
    <div class="panel">
      <div class="panel-header">
        <h2>Recent Signals <span style="font-size:9px;color:#3d444d;margin-left:4px">≥80% = action</span></h2>
        <span class="badge" id="sig-count">0</span>
      </div>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Action</th><th>Entry</th><th>Confidence</th><th>Reasoning</th></tr>
        </thead>
        <tbody id="signals-body">
          <tr><td colspan="5" class="empty">Waiting for signals…</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <div class="panel-header">
        <h2>Trade History</h2>
        <span class="badge" id="hist-count">0</span>
      </div>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&L</th></tr>
        </thead>
        <tbody id="history-body">
          <tr><td colspan="5" class="empty">No closed trades yet</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</main>

<div id="footer">Last refreshed: <span id="last-update">—</span></div>
<div id="toast"></div>

<script>
let prevPrices = {}, prevStats = {}, firstLoad = true;

function confColor(c){return c>=80?'#39d98a':c>=65?'#e3b341':'#8b949e'}
function fmt(n,dp=2){if(n==null||n==='')return'—';const v=Number(n);return isNaN(v)?'—':v.toLocaleString('en-US',{minimumFractionDigits:dp,maximumFractionDigits:dp})}
function fmtPrice(p){if(p==null)return'—';const v=Number(p);if(isNaN(v))return'—';if(v>=1000)return'$'+fmt(v,2);if(v>=1)return'$'+fmt(v,3);return'$'+fmt(v,4)}
function toast(msg,dur=2500){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),dur)}

function update(data) {
  const online = data.bot_online;
  document.getElementById('dot').className = 'dot'+(online?' online':'');
  document.getElementById('status-text').textContent = online?'Bot online':'Bot offline';
  if(data.last_updated){
    const d=new Date(data.last_updated);
    document.getElementById('update-time').textContent='Updated '+d.toLocaleTimeString();
  }

  // Prices bar
  const pb=document.getElementById('prices-bar');
  if(data.prices&&Object.keys(data.prices).length){
    pb.innerHTML=Object.entries(data.prices).map(([sym,price])=>{
      const prev=prevPrices[sym];
      const cls=!prev?'':(price>prev?'up':price<prev?'dn':'');
      const arrow=!prev?'':(price>prev?' ▲':price<prev?' ▼':'');
      return`<div class="price-chip ${cls}"><span class="sym">${sym}</span>${fmtPrice(price)}<span class="chg">${arrow}</span></div>`;
    }).join('');
    prevPrices={...data.prices};
  }

  // Core stats
  const s=data.stats||{};
  const pnl=s.realized_pnl??0;
  document.getElementById('s-total').textContent=s.total_trades??'—';
  document.getElementById('s-wins').textContent=s.wins??'—';
  document.getElementById('s-losses').textContent=s.losses??'—';
  document.getElementById('s-acc').textContent=(s.accuracy_pct??0)+'%';
  document.getElementById('s-open').textContent=s.open_positions??'—';
  document.getElementById('s-open-sub').textContent=`${s.open_longs??0}L / ${s.open_shorts??0}S`;
  const pnlEl=document.getElementById('s-pnl');
  const pnlCard=document.getElementById('pnl-card');
  pnlEl.textContent=(pnl>=0?'+':'')+fmt(pnl,4);
  pnlEl.className='value '+(pnl>=0?'pnl pos':'pnl neg');
  pnlCard.className='stat-card '+(pnl>=0?'green':'red');
  if(!firstLoad&&prevStats.realized_pnl!==undefined&&pnl!==prevStats.realized_pnl){
    const diff=pnl-prevStats.realized_pnl;
    toast((diff>=0?'📈 +':'📉 ')+fmt(diff,4)+' USDT');
  }
  prevStats={...s};

  // Performance stats row
  const pf=s.profit_factor??0;
  const aw=s.avg_win??0;
  const al=s.avg_loss??0;
  const rr=al>0?Math.round(aw/al*100)/100:0;
  document.getElementById('s-pf').textContent=pf>0?fmt(pf,2):'—';
  document.getElementById('s-aw').textContent=aw>0?'+'+fmt(aw,4):'—';
  document.getElementById('s-al').textContent=al>0?'-'+fmt(al,4):'—';
  document.getElementById('s-rr').textContent=rr>0?fmt(rr,2)+'x':'—';
  // Color profit factor
  const pfEl=document.getElementById('s-pf');
  pfEl.style.color=pf>=1.5?'var(--green)':pf>=1.0?'var(--gold)':'var(--red)';

  // Positions
  const pos=data.positions||[];
  document.getElementById('pos-count').textContent=pos.length;
  const pl=document.getElementById('positions-list');
  if(!pos.length){pl.innerHTML='<div class="empty">No open positions</div>';}
  else{
    pl.innerHTML=pos.map(p=>{
      const isShort=p.side==='SHORT';
      const cur=(data.prices||{})[p.symbol]||p.entry;
      const unreal=isShort?(p.entry-cur)*p.quantity:(cur-p.entry)*p.quantity;
      const cls=unreal>=0?'pos':'neg';
      const sign=unreal>=0?'+':'';
      const slPrice=isShort?p.entry*(1+((p.stop_loss_pct||2)/100)):p.entry*(1-((p.stop_loss_pct||2)/100));
      const tpPrice=isShort?p.entry*(1-((p.take_profit_pct||4)/100)):p.entry*(1+((p.take_profit_pct||4)/100));
      const sideColor=isShort?'var(--red)':'var(--green)';
      return`<div class="pos-card${isShort?' short':''}">
        <div class="pos-header">
          <span class="pos-sym">${p.symbol}</span>
          <span class="pill ${isShort?'short':'long'}">${p.side||'LONG'}</span>
        </div>
        <div class="pos-detail">
          <span>Entry<span class="val">${fmtPrice(p.entry)}</span></span>
          <span>Current<span class="val">${fmtPrice(cur)}</span></span>
          <span>Qty<span class="val">${p.quantity}</span></span>
          <span>Unreal P&L<span class="val pnl ${cls}">${sign}${fmt(unreal,4)}</span></span>
        </div>
        <div class="pos-sl-tp">
          <span class="sl-tag">SL ${fmtPrice(slPrice)}</span>
          <span class="tp-tag">TP ${fmtPrice(tpPrice)}</span>
        </div>
      </div>`;
    }).join('');
  }

  // Strategy leaderboard
  const strats=data.strategy_stats||{};
  const sb2=document.getElementById('strat-body');
  const stratKeys=Object.keys(strats);
  if(!stratKeys.length){sb2.innerHTML='<div class="empty">No strategy data yet</div>';}
  else{
    const maxPnl=Math.max(...stratKeys.map(k=>Math.abs(strats[k].pnl||0)),1);
    sb2.innerHTML=stratKeys.sort((a,b)=>{
      const wa=strats[a],wb=strats[b];
      const wra=wa.wins+wa.losses>0?wa.wins/(wa.wins+wa.losses):0;
      const wrb=wb.wins+wb.losses>0?wb.wins/(wb.wins+wb.losses):0;
      return wrb-wra;
    }).map(k=>{
      const st=strats[k];
      const total=st.wins+st.losses;
      const wr=total>0?Math.round(st.wins/total*100):0;
      const pnlSign=st.pnl>=0?'+':'';
      const barColor=wr>=55?'var(--green)':wr>=45?'var(--gold)':'var(--red)';
      return`<div class="strat-row">
        <span class="strat-name">${k}</span>
        <div class="strat-bar-wrap"><div class="strat-bar-fill" style="width:${wr}%;background:${barColor}"></div></div>
        <span class="strat-meta" style="color:${barColor}">${total} trades | ${wr}% WR | ${pnlSign}${fmt(st.pnl,4)}</span>
      </div>`;
    }).join('');
  }

  // Blacklist
  const bans=data.blacklisted_coins||{};
  const banKeys=Object.keys(bans);
  document.getElementById('ban-count').textContent=banKeys.length;
  const blBody=document.getElementById('blacklist-body');
  if(!banKeys.length){blBody.innerHTML='<div class="empty">✅ No coins blacklisted</div>';}
  else{
    blBody.innerHTML=banKeys.map(sym=>{
      const until=bans[sym];
      const hrs=Math.max(0,(until*1000-Date.now())/3600000).toFixed(1);
      return`<div class="ban-row">
        <span class="ban-sym">⛔ ${sym}</span>
        <span class="ban-timer">${hrs}h remaining</span>
      </div>`;
    }).join('');
  }

  // Per-coin breakdown
  const coinStats=s.coin_stats||{};
  const coinKeys=Object.keys(coinStats).sort((a,b)=>{
    const wa=coinStats[a],wb=coinStats[b];
    const ta=wa.wins+wa.losses,tb=wb.wins+wb.losses;
    return tb-ta;
  });
  document.getElementById('coin-count').textContent=coinKeys.length;
  const cb=document.getElementById('coin-body');
  if(!coinKeys.length){cb.innerHTML='<tr><td colspan="5" class="empty">No trade data yet</td></tr>';}
  else{
    cb.innerHTML=coinKeys.map(sym=>{
      const cs=coinStats[sym];
      const total=cs.wins+cs.losses;
      const wr=total>0?Math.round(cs.wins/total*100):0;
      const pnlSign=cs.pnl>=0?'+':'';
      const pnlCls=cs.pnl>=0?'pos':'neg';
      const wrColor=wr>=55?'var(--green)':wr>=40?'var(--gold)':'var(--red)';
      const isBanned=banKeys.includes(sym);
      const status=isBanned?'<span class="pill sell">BANNED</span>':'<span class="pill hold">Active</span>';
      return`<tr>
        <td><strong style="color:var(--white)">${sym}</strong></td>
        <td>${total}</td>
        <td>
          <span style="color:${wrColor};font-weight:600">${wr}%</span>
          <div style="margin-top:3px;height:3px;width:${wr}px;max-width:100px;background:${wrColor};border-radius:2px"></div>
        </td>
        <td class="pnl ${pnlCls}">${pnlSign}${fmt(cs.pnl,4)}</td>
        <td>${status}</td>
      </tr>`;
    }).join('');
  }

  // Signals
  const sigs=(data.signals||[]).slice().reverse();
  document.getElementById('sig-count').textContent=sigs.length;
  const sigBody=document.getElementById('signals-body');
  if(!sigs.length){sigBody.innerHTML='<tr><td colspan="5" class="empty">Waiting…</td></tr>';}
  else{
    sigBody.innerHTML=sigs.slice(0,25).map(s=>{
      const ac=(s.action||'HOLD').toLowerCase();
      const conf=s.confidence||0;
      const col=confColor(conf);
      const bar=`<div class="conf-wrap"><div class="conf-bar"><div class="conf-fill" style="width:${conf}%;background:${col}"></div></div><span class="conf-pct" style="color:${col}">${conf}%</span></div>`;
      const reason=(s.reasoning||'').replace(/"/g,'&quot;');
      return`<tr>
        <td><strong style="color:var(--white)">${s.symbol}</strong></td>
        <td><span class="pill ${ac}">${s.action}</span></td>
        <td style="font-variant-numeric:tabular-nums">${fmtPrice(s.entry)}</td>
        <td>${bar}</td>
        <td class="reason-cell" title="${reason}">${s.reasoning||'—'}</td>
      </tr>`;
    }).join('');
  }

  // Trade history — show up to 200
  const hist=(data.trade_history||[]).slice().reverse();
  document.getElementById('hist-count').textContent=hist.length;
  const hb=document.getElementById('history-body');
  if(!hist.length){hb.innerHTML='<tr><td colspan="5" class="empty">No closed trades yet</td></tr>';}
  else{
    hb.innerHTML=hist.slice(0,200).map(t=>{
      const p=t.pnl??0;
      const cls=p>=0?'pos':'neg';
      const sign=p>=0?'+':'';
      const icon=p>=0?'✅':'❌';
      return`<tr>
        <td><strong style="color:var(--white)">${t.symbol}</strong></td>
        <td><span class="pill ${(t.side||'').toLowerCase()}">${t.side||'—'}</span></td>
        <td style="font-variant-numeric:tabular-nums">${fmtPrice(t.entry)}</td>
        <td style="font-variant-numeric:tabular-nums">${t.exit?fmtPrice(t.exit):'—'}</td>
        <td class="pnl ${cls}">${icon} ${sign}${fmt(p,4)}</td>
      </tr>`;
    }).join('');
  }

  document.getElementById('last-update').textContent=new Date().toLocaleTimeString();
  firstLoad=false;
}

async function poll(){
  try{
    const r=await fetch('/api/all');
    if(r.ok)update(await r.json());
    else throw new Error(r.status);
  }catch(e){
    document.getElementById('status-text').textContent='Disconnected';
    document.getElementById('dot').className='dot';
  }
}

poll();
setInterval(poll,5000);
</script>
</body>
</html>"""
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CryptoBot — Live Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080c10;--bg1:#0d1117;--bg2:#141b22;--bg3:#1c2430;
  --border:#21262d;--border2:#30363d;
  --green:#39d98a;--green-dim:#1a3a2a;--green-glow:rgba(57,217,138,.2);
  --red:#f85149;--red-dim:#3a1a1a;--red-glow:rgba(248,81,73,.15);
  --gold:#e3b341;--blue:#58a6ff;--muted:#8b949e;--text:#c9d1d9;--white:#f0f6fc;
  --font:'Inter',system-ui,sans-serif;
}
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh;font-size:13px}
/* ── Header ── */
header{display:flex;align-items:center;justify-content:space-between;
       padding:12px 20px;background:var(--bg1);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:34px;height:34px;background:linear-gradient(135deg,#39d98a,#1a8a55);
           border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 0 16px var(--green-glow)}
.logo-text h1{font-size:14px;font-weight:700;letter-spacing:.4px;color:var(--white)}
.logo-text p{font-size:10px;color:var(--muted);letter-spacing:1.5px;text-transform:uppercase}
.status-bar{display:flex;align-items:center;gap:12px}
.status{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);
        background:var(--bg2);padding:5px 12px;border-radius:20px;border:1px solid var(--border)}
.dot{width:7px;height:7px;border-radius:50%;background:#444;transition:all .3s}
.dot.online{background:var(--green);box-shadow:0 0 8px var(--green)}
#update-time{font-size:11px;color:var(--muted)}
/* ── Price bar ── */
.prices-bar{display:flex;gap:8px;padding:10px 20px;background:var(--bg1);
            border-bottom:1px solid var(--border);flex-wrap:wrap;overflow-x:auto}
.price-chip{background:var(--bg2);border:1px solid var(--border);border-radius:8px;
            padding:5px 12px;font-size:12px;font-weight:600;cursor:default;
            transition:border-color .3s,transform .15s;white-space:nowrap}
.price-chip:hover{transform:translateY(-1px)}
.price-chip .sym{color:var(--muted);font-weight:400;font-size:10px;margin-right:5px;letter-spacing:.5px}
.price-chip.up{border-color:#1e4d35;color:var(--green)}
.price-chip.dn{border-color:#4d1e1e;color:var(--red)}
.price-chip .chg{font-size:10px;margin-left:4px;opacity:.7}
/* ── Main layout ── */
main{padding:16px 20px;display:grid;gap:14px;max-width:1600px;margin:0 auto}
/* ── Stats row ── */
.stats-row{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:1100px){.stats-row{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.stats-row{grid-template-columns:repeat(2,1fr)}}
.stat-card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;
           padding:14px 16px;position:relative;overflow:hidden;transition:border-color .3s}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--border)}
.stat-card.green::before{background:linear-gradient(90deg,var(--green),transparent)}
.stat-card.red::before{background:linear-gradient(90deg,var(--red),transparent)}
.stat-card.blue::before{background:linear-gradient(90deg,var(--blue),transparent)}
.stat-card.gold::before{background:linear-gradient(90deg,var(--gold),transparent)}
.stat-card .label{font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);margin-bottom:10px}
.stat-card .value{font-size:28px;font-weight:700;color:var(--white);line-height:1;letter-spacing:-1px}
.stat-card .sub{font-size:10px;color:var(--muted);margin-top:6px}
.stat-card.green .value{color:var(--green)}
.stat-card.red .value{color:var(--red)}
.stat-card.blue .value{color:var(--blue)}
.stat-card.gold .value{color:var(--gold)}
/* ── Positions ── */
.panel{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:0;overflow:hidden}
.panel-header{display:flex;align-items:center;justify-content:space-between;
              padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bg3)}
.panel-header h2{font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted);font-weight:600}
.badge{background:var(--bg);border:1px solid var(--border2);border-radius:20px;
       padding:1px 8px;font-size:10px;color:var(--muted);font-weight:600}
/* ── Positions grid ── */
.pos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;padding:14px}
.pos-card{background:var(--bg3);border:1px solid var(--border2);border-radius:10px;
          padding:12px 14px;transition:border-color .3s}
.pos-card:hover{border-color:var(--green)}
.pos-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.pos-sym{font-weight:700;font-size:14px;color:var(--white)}
.pos-detail{display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:11px;color:var(--muted)}
.pos-detail span{display:flex;flex-direction:column;gap:1px}
.pos-detail .val{color:var(--text);font-weight:500}
.pos-pnl{font-size:16px;font-weight:700;text-align:right}
.pos-pnl.pos{color:var(--green)}
.pos-pnl.neg{color:var(--red)}
.pos-sl-tp{display:flex;gap:8px;margin-top:8px;font-size:10px}
.sl-tag,.tp-tag{padding:2px 7px;border-radius:4px;font-weight:600}
.sl-tag{background:var(--red-dim);color:var(--red);border:1px solid #f8514940}
.tp-tag{background:var(--green-dim);color:var(--green);border:1px solid #39d98a40}
/* ── Tables ── */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:800px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse}
th{text-align:left;color:var(--muted);font-weight:500;padding:10px 14px;
   text-transform:uppercase;font-size:9px;letter-spacing:.8px;border-bottom:1px solid var(--border)}
td{padding:9px 14px;border-bottom:1px solid var(--border);vertical-align:middle;
   transition:background .15s}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg3)}
/* ── Pills ── */
.pill{display:inline-flex;align-items:center;padding:2px 9px;border-radius:20px;
      font-size:10px;font-weight:700;letter-spacing:.3px}
.pill.buy {background:var(--green-dim);color:var(--green);border:1px solid #39d98a33}
.pill.sell{background:var(--red-dim);color:var(--red);border:1px solid #f8514933}
.pill.hold{background:#1c2430;color:var(--muted);border:1px solid var(--border)}
.pill.long{background:var(--green-dim);color:var(--green);border:1px solid #39d98a33}
/* ── Confidence bar ── */
.conf-wrap{display:flex;align-items:center;gap:6px}
.conf-bar{height:4px;border-radius:2px;background:var(--bg3);width:60px;flex-shrink:0}
.conf-fill{height:100%;border-radius:2px;transition:width .5s}
.conf-pct{font-size:11px;font-weight:600;min-width:28px}
/* ── PnL ── */
.pnl.pos{color:var(--green)}
.pnl.neg{color:var(--red)}
/* ── Empty state ── */
.empty{color:var(--muted);font-size:12px;padding:32px;text-align:center;opacity:.6}
/* ── Reasoning tooltip ── */
td[title]{cursor:help;position:relative}
.reason-cell{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
             color:var(--muted);font-size:11px}
/* ── Mini chart ── */
.mini-chart{width:70px;height:28px}
/* ── Footer ── */
#footer{font-size:10px;color:#3d444d;padding:8px 20px 20px;text-align:right}
/* ── Alerts/Toast ── */
#toast{position:fixed;bottom:20px;right:20px;background:var(--bg3);border:1px solid var(--border2);
       border-radius:10px;padding:10px 16px;font-size:12px;color:var(--text);
       box-shadow:0 8px 32px #000a;opacity:0;transform:translateY(10px);
       transition:all .3s;z-index:999;pointer-events:none}
#toast.show{opacity:1;transform:translateY(0)}
/* ── Scrollbar ── */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🤖</div>
    <div class="logo-text">
      <h1>CRYPTOBOT</h1>
      <p>Live Dashboard</p>
    </div>
  </div>
  <div class="status-bar">
    <div class="status">
      <div class="dot" id="dot"></div>
      <span id="status-text">Connecting…</span>
    </div>
    <span id="update-time"></span>
  </div>
</header>

<div class="prices-bar" id="prices-bar">
  <div class="price-chip"><span class="sym">Loading…</span></div>
</div>

<main>
  <!-- Stats -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="label">Total Trades</div>
      <div class="value" id="s-total">—</div>
      <div class="sub">executed</div>
    </div>
    <div class="stat-card green">
      <div class="label">Wins</div>
      <div class="value" id="s-wins">—</div>
      <div class="sub">profitable closes</div>
    </div>
    <div class="stat-card red">
      <div class="label">Losses</div>
      <div class="value" id="s-losses">—</div>
      <div class="sub">losing closes</div>
    </div>
    <div class="stat-card blue">
      <div class="label">Accuracy</div>
      <div class="value" id="s-acc">—</div>
      <div class="sub">win rate</div>
    </div>
    <div class="stat-card" id="pnl-card">
      <div class="label">Realised P&L</div>
      <div class="value" id="s-pnl">—</div>
      <div class="sub">USDT</div>
    </div>
    <div class="stat-card gold">
      <div class="label">Open Positions</div>
      <div class="value" id="s-open">—</div>
      <div class="sub">active</div>
    </div>
  </div>

  <!-- Open Positions -->
  <div class="panel">
    <div class="panel-header">
      <h2>Open Positions</h2>
      <span class="badge" id="pos-count">0</span>
    </div>
    <div class="pos-grid" id="positions-list">
      <div class="empty">No open positions</div>
    </div>
  </div>

  <!-- Signals + History -->
  <div class="grid2">
    <div class="panel">
      <div class="panel-header">
        <h2>Recent Signals <span style="font-size:9px;color:#3d444d;margin-left:4px">≥80% = action</span></h2>
        <span class="badge" id="sig-count">0</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Symbol</th><th>Action</th><th>Entry</th><th>Confidence</th><th>Reasoning</th>
          </tr>
        </thead>
        <tbody id="signals-body">
          <tr><td colspan="5" class="empty">Waiting for signals…</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <div class="panel-header">
        <h2>Trade History</h2>
        <span class="badge" id="hist-count">0</span>
      </div>
      <table>
        <thead>
          <tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&L</th></tr>
        </thead>
        <tbody id="history-body">
          <tr><td colspan="5" class="empty">No closed trades yet</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</main>

<div id="footer">Last refreshed: <span id="last-update">—</span></div>
<div id="toast"></div>

<script>
let prevPrices  = {};
let prevStats   = {};
let firstLoad   = true;

function confColor(c) {
  if (c >= 80) return '#39d98a';
  if (c >= 65) return '#e3b341';
  return '#8b949e';
}

function fmt(n, dp=2) {
  if (n == null || n === '') return '—';
  const v = Number(n);
  if (isNaN(v)) return '—';
  return v.toLocaleString('en-US', {minimumFractionDigits:dp, maximumFractionDigits:dp});
}

function fmtPrice(p) {
  if (p == null) return '—';
  const v = Number(p);
  if (isNaN(v)) return '—';
  if (v >= 1000) return '$' + fmt(v, 2);
  if (v >= 1)    return '$' + fmt(v, 3);
  return '$' + fmt(v, 4);
}

function toast(msg, dur=2500) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), dur);
}

function animateValue(el, newVal) {
  if (!el) return;
  el.style.transition = 'opacity .2s';
  el.style.opacity = '0';
  setTimeout(() => {
    el.textContent = newVal;
    el.style.opacity = '1';
  }, 180);
}

function update(data) {
  const online = data.bot_online;
  document.getElementById('dot').className = 'dot' + (online ? ' online' : '');
  document.getElementById('status-text').textContent = online ? 'Bot online' : 'Bot offline';
  if (data.last_updated) {
    const d = new Date(data.last_updated);
    document.getElementById('update-time').textContent = 'Updated ' + d.toLocaleTimeString();
  }

  // ── Prices bar ──
  const pb = document.getElementById('prices-bar');
  if (data.prices && Object.keys(data.prices).length) {
    pb.innerHTML = Object.entries(data.prices).map(([sym, price]) => {
      const prev = prevPrices[sym];
      const cls  = !prev ? '' : (price > prev ? 'up' : price < prev ? 'dn' : '');
      const arrow = !prev ? '' : (price > prev ? ' ▲' : price < prev ? ' ▼' : '');
      return `<div class="price-chip ${cls}">
        <span class="sym">${sym}</span>${fmtPrice(price)}<span class="chg">${arrow}</span>
      </div>`;
    }).join('');
    prevPrices = {...data.prices};
  }

  // ── Stats ──
  const s   = data.stats || {};
  const pnl = s.realized_pnl ?? 0;

  document.getElementById('s-total').textContent = s.total_trades ?? '—';
  document.getElementById('s-wins').textContent  = s.wins ?? '—';
  document.getElementById('s-losses').textContent = s.losses ?? '—';
  document.getElementById('s-acc').textContent   = (s.accuracy_pct ?? 0) + '%';
  document.getElementById('s-open').textContent  = s.open_positions ?? '—';

  const pnlEl  = document.getElementById('s-pnl');
  const pnlCard = document.getElementById('pnl-card');
  pnlEl.textContent  = (pnl >= 0 ? '+' : '') + fmt(pnl, 4);
  pnlEl.className    = 'value ' + (pnl >= 0 ? 'pnl pos' : 'pnl neg');
  pnlCard.className  = 'stat-card ' + (pnl >= 0 ? 'green' : 'red');

  // Detect PnL change and notify
  if (!firstLoad && prevStats.realized_pnl !== undefined && pnl !== prevStats.realized_pnl) {
    const diff = pnl - prevStats.realized_pnl;
    toast((diff >= 0 ? '📈 +' : '📉 ') + fmt(diff, 4) + ' USDT');
  }
  prevStats = {...s};

  // ── Positions ──
  const pos = data.positions || [];
  document.getElementById('pos-count').textContent = pos.length;
  const pl = document.getElementById('positions-list');
  if (!pos.length) {
    pl.innerHTML = '<div class="empty">No open positions</div>';
  } else {
    pl.innerHTML = pos.map(p => {
      const cur    = (data.prices || {})[p.symbol] || p.entry;
      const unreal = (cur - p.entry) * p.quantity;
      const cls    = unreal >= 0 ? 'pos' : 'neg';
      const sign   = unreal >= 0 ? '+' : '';
      const slPrice = p.entry * (1 - (p.stop_loss_pct || 2) / 100);
      const tpPrice = p.entry * (1 + (p.take_profit_pct || 4) / 100);
      return `<div class="pos-card">
        <div class="pos-header">
          <span class="pos-sym">${p.symbol}</span>
          <span class="pill long">LONG</span>
        </div>
        <div class="pos-detail">
          <span>Entry<span class="val">${fmtPrice(p.entry)}</span></span>
          <span>Current<span class="val">${fmtPrice(cur)}</span></span>
          <span>Qty<span class="val">${p.quantity}</span></span>
          <span>Unreal P&L<span class="val pnl ${cls}">${sign}${fmt(unreal,4)}</span></span>
        </div>
        <div class="pos-sl-tp">
          <span class="sl-tag">SL ${fmtPrice(slPrice)}</span>
          <span class="tp-tag">TP ${fmtPrice(tpPrice)}</span>
        </div>
      </div>`;
    }).join('');
  }

  // ── Signals table ──
  const sigs = (data.signals || []).slice().reverse();
  document.getElementById('sig-count').textContent = sigs.length;
  const sb = document.getElementById('signals-body');
  if (!sigs.length) {
    sb.innerHTML = '<tr><td colspan="5" class="empty">Waiting for signals…</td></tr>';
  } else {
    sb.innerHTML = sigs.slice(0,20).map(s => {
      const ac   = (s.action || 'HOLD').toLowerCase();
      const conf = s.confidence || 0;
      const col  = confColor(conf);
      const bar  = `<div class="conf-wrap">
        <div class="conf-bar"><div class="conf-fill" style="width:${conf}%;background:${col}"></div></div>
        <span class="conf-pct" style="color:${col}">${conf}%</span>
      </div>`;
      const reason = (s.reasoning || '').replace(/"/g,'&quot;');
      return `<tr>
        <td><strong style="color:var(--white)">${s.symbol}</strong></td>
        <td><span class="pill ${ac}">${s.action}</span></td>
        <td style="font-variant-numeric:tabular-nums">${fmtPrice(s.entry)}</td>
        <td>${bar}</td>
        <td class="reason-cell" title="${reason}">${s.reasoning || '—'}</td>
      </tr>`;
    }).join('');
  }

  // ── Trade history ──
  const hist = (data.trade_history || []).slice().reverse();
  document.getElementById('hist-count').textContent = hist.length;
  const hb = document.getElementById('history-body');
  if (!hist.length) {
    hb.innerHTML = '<tr><td colspan="5" class="empty">No closed trades yet</td></tr>';
  } else {
    hb.innerHTML = hist.slice(0,20).map(t => {
      const pnl  = t.pnl ?? 0;
      const cls  = pnl >= 0 ? 'pos' : 'neg';
      const sign = pnl >= 0 ? '+' : '';
      const icon = pnl >= 0 ? '✅' : '❌';
      return `<tr>
        <td><strong style="color:var(--white)">${t.symbol}</strong></td>
        <td><span class="pill ${(t.side||'').toLowerCase()}">${t.side || '—'}</span></td>
        <td style="font-variant-numeric:tabular-nums">${fmtPrice(t.entry)}</td>
        <td style="font-variant-numeric:tabular-nums">${t.exit ? fmtPrice(t.exit) : '—'}</td>
        <td class="pnl ${cls}">${icon} ${sign}${fmt(pnl,4)}</td>
      </tr>`;
    }).join('');
  }

  document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
  firstLoad = false;
}

async function poll() {
  try {
    const r = await fetch('/api/all');
    if (r.ok) update(await r.json());
    else throw new Error(r.status);
  } catch(e) {
    document.getElementById('status-text').textContent = 'Disconnected';
    document.getElementById('dot').className = 'dot';
  }
}

poll();
setInterval(poll, 5000);
</script>
</body>
</html>"""

# ── Routes ────────────────────────────────────────────────────────────────────
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
            if fresh.get("prices"):
                state["prices"]    = fresh["prices"]
            state["bot_online"]    = fresh.get("bot_online", True)
            state["last_updated"]  = datetime.now(timezone.utc).isoformat()
    with state_lock:
        return jsonify({
            "stats":         state["stats"],
            "positions":     state["positions"],
            "prices":        state["prices"],
            "signals":       state["signals"][-25:],
            "trade_history": state["trade_history"][-200:],
            "strategy_stats":   fresh.get("strategy_stats", {}),
            "blacklisted_coins": fresh.get("blacklisted_coins", {}),
            "last_updated":  state["last_updated"],
            "bot_online":    state["bot_online"],
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

# ── Background poller ─────────────────────────────────────────────────────────
def poll_loop():
    import aiohttp

    async def fetch():
        BASE_URL = "https://testnet.binance.vision"
        SYMBOLS  = os.environ.get("SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    prices = {}
                    for sym in SYMBOLS:
                        async with session.get(
                            f"{BASE_URL}/api/v3/ticker/price?symbol={sym}",
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as r:
                            if r.status == 200:
                                d = await r.json()
                                prices[sym] = float(d["price"])

                    bot_state = _read_bot_state()
                    with state_lock:
                        if prices:
                            state["prices"] = prices
                        state["last_updated"] = datetime.now(timezone.utc).isoformat()
                        state["bot_online"]   = bool(bot_state)
                        if bot_state:
                            state["stats"]         = bot_state.get("stats",         state["stats"])
                            state["positions"]      = bot_state.get("positions",     [])
                            state["signals"]        = bot_state.get("signals",       [])
                            state["trade_history"]  = bot_state.get("trade_history", [])
                except Exception as e:
                    log.warning(f"Poll error: {e}")
                    with state_lock:
                        state["bot_online"] = False
                await asyncio.sleep(10)

    asyncio.run(fetch())

def _read_bot_state() -> dict:
    try:
        with open("bot_state.json") as f:
            return json.load(f)
    except Exception:
        return {}

threading.Thread(target=poll_loop, daemon=True).start()

if __name__ == "__main__":
    print("=" * 55)
    print("  📊 CryptoBot Dashboard → http://localhost:5000")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, debug=False)
