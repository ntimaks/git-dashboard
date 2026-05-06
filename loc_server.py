#!/usr/bin/env python3
"""
LOC dashboard server — tracks lines of code growth across any local git repo.
Run from anywhere: python3 loc_server.py
Then open:        http://localhost:8765
"""
import http.server
import json
import subprocess
import threading
import os
from datetime import datetime

DEFAULT_REPO = "/Users/nikolasstimaks/Local Sites/hm-local/app/hackmotion-web-frontend"
PORT = 8765
EXTS = ('.ts', '.tsx', '.js', '.jsx', '.css', '.scss')
EXCLUDE = ('node_modules', '/.next/', '/dist/')

_cache = {'data': [], 'updated_at': None, 'refreshing': False, 'repo_path': DEFAULT_REPO, 'repo_name': ''}
_lock = threading.Lock()


def repo_name(path):
    return os.path.basename(path.rstrip('/\\'))


def validate_git_repo(path):
    """Returns None if valid, error string if not."""
    if not os.path.isdir(path):
        return f'Directory not found: {path}'
    r = subprocess.run(['git', 'rev-parse', '--git-dir'], capture_output=True, cwd=path)
    if r.returncode != 0:
        return f'Not a git repository: {path}'
    return None


def get_weekly_commits(path):
    r = subprocess.run(
        ['git', 'log', '--reverse', '--format=%H %ad', '--date=format:%Y-%W'],
        capture_output=True, text=True, cwd=path
    )
    seen = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hash_, week = parts
            if week not in seen:
                seen[week] = hash_
    return list(seen.values())


def count_lines_at(hash_, path):
    r = subprocess.run(
        ['git', 'ls-tree', '-r', '--name-only', hash_],
        capture_output=True, text=True, cwd=path
    )
    files = [
        f for f in r.stdout.splitlines()
        if f.endswith(EXTS) and not any(x in f for x in EXCLUDE)
    ]
    if not files:
        return 0, 0
    blob_specs = '\n'.join(f'{hash_}:{f}' for f in files)
    cat = subprocess.run(
        ['git', 'cat-file', '--batch'],
        input=blob_specs, capture_output=True, text=True, errors='replace', cwd=path
    )
    return cat.stdout.count('\n'), len(files)


def get_date_for_commit(hash_, path):
    r = subprocess.run(
        ['git', 'log', '-1', '--format=%ad', '--date=format:%Y-%m-%d', hash_],
        capture_output=True, text=True, cwd=path
    )
    return r.stdout.strip()


def do_refresh(path=None):
    with _lock:
        path = path or _cache['repo_path']
    print(f'Counting LOC in {path}...', flush=True)
    commits = get_weekly_commits(path)
    results = []
    for i, hash_ in enumerate(commits):
        lines, files = count_lines_at(hash_, path)
        if lines == 0:
            continue
        date = get_date_for_commit(hash_, path)
        results.append({'date': date, 'lines': lines, 'files': files})
        print(f'  [{i+1}/{len(commits)}] {date}: {lines:,} lines', flush=True)

    updated_at = datetime.now().strftime('%b %d, %Y %H:%M')
    with _lock:
        _cache['data'] = results
        _cache['updated_at'] = updated_at
        _cache['repo_path'] = path
        _cache['repo_name'] = repo_name(path)
        _cache['refreshing'] = False
    print(f'Done. {len(results)} snapshots.\n', flush=True)
    return results, updated_at


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LOC Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
  <style>
    :root {
      --bg:#0f0f13; --card:#1a1a26; --header:#12121c;
      --border:#2a2a3d; --t1:#e2e8f0; --t2:#64748b; --t3:#3f4a5e;
      --purple:#a78bfa; --green:#34d399; --blue:#60a5fa; --orange:#fb923c;
      --red:#f87171; --gap:16px; --r:10px;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg); color:var(--t1); padding:24px; }
    .wrap { max-width:1400px; margin:0 auto; }

    /* header */
    header { background:var(--header); border:1px solid var(--border); border-radius:var(--r); padding:16px 24px; margin-bottom:var(--gap); }
    .header-top { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    header h1 { font-size:16px; font-weight:600; }
    header .sub { font-size:11px; color:var(--t2); margin-top:2px; }
    .header-right { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    #last-updated { font-size:11px; color:var(--t2); }

    /* range selector */
    .range-bar { display:flex; gap:4px; }
    .range-btn { background:transparent; color:var(--t2); border:1px solid var(--border); border-radius:5px; padding:5px 11px; font-size:12px; cursor:pointer; transition:all .15s; }
    .range-btn:hover { color:var(--t1); border-color:#3f4a5e; }
    .range-btn.active { background:rgba(167,139,250,.15); color:var(--purple); border-color:rgba(167,139,250,.4); font-weight:600; }

    /* repo row */
    .repo-row { display:flex; align-items:center; gap:10px; margin-top:14px; padding-top:14px; border-top:1px solid var(--border); flex-wrap:wrap; }
    .repo-label { font-size:11px; color:var(--t2); white-space:nowrap; }
    .repo-path-display { font-size:12px; color:var(--t1); font-family:monospace; background:rgba(255,255,255,.04); border:1px solid var(--border); border-radius:5px; padding:5px 10px; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer; }
    .repo-path-display:hover { border-color:rgba(167,139,250,.4); }
    #repo-input { font-size:12px; color:var(--t1); font-family:monospace; background:rgba(255,255,255,.06); border:1px solid rgba(167,139,250,.5); border-radius:5px; padding:5px 10px; flex:1; min-width:200px; outline:none; display:none; }
    #repo-input:focus { border-color:var(--purple); }
    #repo-input.visible { display:block; }
    .repo-path-display.hidden { display:none; }

    /* buttons */
    .btn { display:inline-flex; align-items:center; gap:6px; border-radius:6px; padding:6px 13px; font-size:12px; font-weight:500; cursor:pointer; border:1px solid; transition:background .15s,opacity .15s; white-space:nowrap; }
    .btn:disabled { opacity:.45; cursor:not-allowed; }
    .btn-purple { background:rgba(167,139,250,.12); color:var(--purple); border-color:rgba(167,139,250,.3); }
    .btn-purple:hover:not(:disabled) { background:rgba(167,139,250,.22); }
    .btn-green { background:rgba(52,211,153,.1); color:var(--green); border-color:rgba(52,211,153,.3); }
    .btn-green:hover:not(:disabled) { background:rgba(52,211,153,.2); }
    .btn-ghost { background:transparent; color:var(--t2); border-color:var(--border); font-size:11px; padding:5px 10px; }
    .btn-ghost:hover:not(:disabled) { color:var(--t1); border-color:#3f4a5e; }
    .btn svg { width:13px; height:13px; flex-shrink:0; }
    .spinning svg { animation:spin 1s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }

    #repo-error { font-size:11px; color:var(--red); display:none; }
    #repo-error.visible { display:block; }

    /* kpi */
    .kpi-row { display:grid; grid-template-columns:repeat(4,1fr); gap:var(--gap); margin-bottom:var(--gap); }
    .kpi { background:var(--card); border:1px solid var(--border); border-radius:var(--r); padding:18px 20px; }
    .kpi-label { font-size:11px; color:var(--t2); text-transform:uppercase; letter-spacing:.07em; margin-bottom:7px; }
    .kpi-value { font-size:1.9rem; font-weight:700; line-height:1; margin-bottom:5px; }
    .kpi-sub { font-size:11px; color:var(--t2); }
    .c-purple{color:var(--purple);} .c-green{color:var(--green);} .c-blue{color:var(--blue);} .c-orange{color:var(--orange);}

    /* charts */
    .chart-row { display:grid; grid-template-columns:2fr 1fr; gap:var(--gap); margin-bottom:var(--gap); }
    .chart-row-2 { display:grid; grid-template-columns:1fr 1fr; gap:var(--gap); margin-bottom:var(--gap); }
    .chart-box { background:var(--card); border:1px solid var(--border); border-radius:var(--r); padding:18px 22px; }
    .chart-box h3 { font-size:13px; font-weight:600; margin-bottom:3px; }
    .chart-box .csub { font-size:11px; color:var(--t2); margin-bottom:16px; }
    canvas { max-height:280px; }

    /* table */
    .table-box { background:var(--card); border:1px solid var(--border); border-radius:var(--r); padding:18px 22px; margin-bottom:var(--gap); overflow-x:auto; }
    .table-box h3 { font-size:13px; font-weight:600; margin-bottom:14px; }
    table { width:100%; border-collapse:collapse; font-size:12px; }
    th { text-align:left; padding:7px 11px; border-bottom:1px solid var(--border); color:var(--t2); font-size:11px; text-transform:uppercase; letter-spacing:.05em; white-space:nowrap; }
    td { padding:8px 11px; border-bottom:1px solid rgba(42,42,61,.5); }
    tr:last-child td { border-bottom:none; }
    tr:hover td { background:rgba(167,139,250,.04); }
    .tr { text-align:right; }
    .pos{color:var(--green);} .neg{color:var(--red);}
    .bar-cell { display:flex; align-items:center; gap:7px; }
    .bar-bg { flex:1; height:4px; background:var(--border); border-radius:2px; }
    .bar-fill { height:100%; border-radius:2px; background:var(--purple); }

    footer { font-size:11px; color:var(--t3); text-align:center; padding-top:6px; }

    @media(max-width:900px) {
      .kpi-row { grid-template-columns:repeat(2,1fr); }
      .chart-row,.chart-row-2 { grid-template-columns:1fr; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="header-top">
      <div>
        <h1 id="dash-title">LOC Dashboard</h1>
        <div class="sub">Weekly git snapshots &nbsp;·&nbsp; TS, TSX, JS, JSX, CSS, SCSS</div>
      </div>
      <div class="header-right">
        <div class="range-bar">
          <button class="range-btn" onclick="setRange(3)">3M</button>
          <button class="range-btn" onclick="setRange(6)">6M</button>
          <button class="range-btn active" onclick="setRange(12)">1Y</button>
          <button class="range-btn" onclick="setRange(24)">2Y</button>
          <button class="range-btn" onclick="setRange(0)">All</button>
        </div>
        <span id="last-updated"></span>
        <button class="btn btn-purple" id="refresh-btn" onclick="triggerRefresh()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          Refresh Data
        </button>
      </div>
    </div>

    <div class="repo-row">
      <span class="repo-label">Repo:</span>
      <div class="repo-path-display" id="repo-display" onclick="editRepo()" title="Click to change repo">__REPO_PATH__</div>
      <input class="btn" id="repo-input" type="text" placeholder="/path/to/your/repo" onkeydown="repoKeydown(event)" />
      <button class="btn btn-green" id="set-repo-btn" onclick="setRepo()" style="display:none">Set &amp; Refresh</button>
      <button class="btn btn-ghost" id="cancel-repo-btn" onclick="cancelEdit()" style="display:none">Cancel</button>
      <span id="repo-error"></span>
    </div>
  </header>

  <section class="kpi-row">
    <div class="kpi"><div class="kpi-label">Current LOC</div><div class="kpi-value c-purple" id="kpi-loc">—</div><div class="kpi-sub" id="kpi-loc-sub"></div></div>
    <div class="kpi"><div class="kpi-label">Total Growth</div><div class="kpi-value c-green" id="kpi-growth">—</div><div class="kpi-sub" id="kpi-growth-sub"></div></div>
    <div class="kpi"><div class="kpi-label">Source Files</div><div class="kpi-value c-blue" id="kpi-files">—</div><div class="kpi-sub" id="kpi-files-sub"></div></div>
    <div class="kpi"><div class="kpi-label">Avg LOC / Week</div><div class="kpi-value c-orange" id="kpi-avg">—</div><div class="kpi-sub" id="kpi-avg-sub"></div></div>
  </section>

  <section class="chart-row">
    <div class="chart-box">
      <h3>Lines of Code &amp; File Count Over Time</h3>
      <div class="csub">LOC on left axis (purple) &nbsp;·&nbsp; file count on right axis (green, dashed)</div>
      <canvas id="trendChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>Growth Phase Breakdown</h3>
      <div class="csub">LOC added per quarter</div>
      <canvas id="donutChart"></canvas>
    </div>
  </section>

  <section class="chart-row-2">
    <div class="chart-box">
      <h3>Weekly LOC Added</h3>
      <div class="csub">Net lines added per week</div>
      <canvas id="deltaChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>LOC per File</h3>
      <div class="csub">Average lines per source file over time</div>
      <canvas id="densityChart"></canvas>
    </div>
  </section>

  <section class="table-box">
    <h3>Weekly Snapshot Data</h3>
    <table>
      <thead><tr>
        <th>Date</th><th class="tr">Lines of Code</th><th class="tr">Files</th>
        <th class="tr">LOC / File</th><th class="tr">Week Delta</th>
        <th style="min-width:140px">Progress</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </section>

  <footer>loc-dashboard &nbsp;·&nbsp; served by loc_server.py</footer>
</div>

<script>
const PURPLE='#a78bfa', GREEN='#34d399', BLUE='#60a5fa', ORANGE='#fb923c';
const GRID='rgba(42,42,61,0.8)', TICK='#4a5568';

let charts = {};
let currentData = __INITIAL_DATA__;
let currentRepo = '__REPO_PATH__';
let activeMonths = 12;

function fmt(n) { return n >= 1000 ? (n/1000).toFixed(1)+'k' : String(n); }
function fmtFull(n) { return n.toLocaleString(); }

// dates are ISO "2025-08-29" — display as "Aug 29 '25"
function fmtDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  const mon = d.toLocaleString('en', {month:'short'});
  const yr = String(d.getFullYear()).slice(2);
  return `${mon} ${d.getDate()} '${yr}`;
}

function filterByRange(data, months) {
  if (!months || !data.length) return data;
  const last = new Date(data[data.length-1].date + 'T00:00:00');
  const cutoff = new Date(last);
  cutoff.setMonth(cutoff.getMonth() - months);
  return data.filter(d => new Date(d.date + 'T00:00:00') >= cutoff);
}

function setRange(months) {
  activeMonths = months;
  document.querySelectorAll('.range-btn').forEach(b => {
    const bm = b.textContent === 'All' ? 0
             : b.textContent === '3M'  ? 3
             : b.textContent === '6M'  ? 6
             : b.textContent === '1Y'  ? 12
             : 24;
    b.classList.toggle('active', bm === months);
  });
  renderAll(currentData);
}

// --- Repo switching ---
function editRepo() {
  const input = document.getElementById('repo-input');
  const display = document.getElementById('repo-display');
  input.value = currentRepo;
  input.classList.add('visible');
  display.classList.add('hidden');
  document.getElementById('set-repo-btn').style.display = 'inline-flex';
  document.getElementById('cancel-repo-btn').style.display = 'inline-flex';
  setRepoError('');
  input.focus();
  input.select();
}

function cancelEdit() {
  document.getElementById('repo-input').classList.remove('visible');
  document.getElementById('repo-display').classList.remove('hidden');
  document.getElementById('set-repo-btn').style.display = 'none';
  document.getElementById('cancel-repo-btn').style.display = 'none';
  setRepoError('');
}

function repoKeydown(e) {
  if (e.key === 'Enter') setRepo();
  if (e.key === 'Escape') cancelEdit();
}

function setRepoError(msg) {
  const el = document.getElementById('repo-error');
  el.textContent = msg;
  el.className = 'repo-error' + (msg ? ' visible' : '');
}

async function setRepo() {
  const path = document.getElementById('repo-input').value.trim();
  if (!path || path === currentRepo) { cancelEdit(); return; }

  const btn = document.getElementById('set-repo-btn');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  setRepoError('');

  try {
    const res = await fetch('/api/set-repo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path })
    });
    const json = await res.json();
    if (!res.ok) {
      setRepoError(json.error || 'Invalid repo path');
      return;
    }
    // success — repo is set, now trigger refresh
    currentRepo = path;
    document.getElementById('repo-display').textContent = path;
    cancelEdit();
    await triggerRefresh();
  } catch(e) {
    setRepoError('Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Set & Refresh';
    // Fix innerHTML after textContent
    btn.innerHTML = 'Set &amp; Refresh';
  }
}

// --- Refresh ---
async function triggerRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.classList.add('spinning');
  btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Refreshing…`;
  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || 'Refresh failed');
    currentData = json.data;
    currentRepo = json.repo_path;
    document.getElementById('repo-display').textContent = currentRepo;
    document.getElementById('dash-title').textContent = json.repo_name + ' — LOC Dashboard';
    renderAll(currentData);
    document.getElementById('last-updated').textContent = 'Updated ' + json.updated_at;
  } catch(e) {
    alert('Refresh failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.classList.remove('spinning');
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Refresh Data`;
  }
}

// --- KPIs ---
function updateKPIs(data) {
  if (!data.length) return;
  const last = data[data.length-1], first = data[0];
  const growth = last.lines - first.lines;
  const avg = Math.round(growth / data.length);
  document.getElementById('kpi-loc').textContent = fmt(last.lines);
  document.getElementById('kpi-loc-sub').textContent = 'as of ' + fmtDate(last.date);
  document.getElementById('kpi-growth').textContent = '+' + fmtFull(growth);
  document.getElementById('kpi-growth-sub').textContent = `from ${first.lines} lines at launch`;
  document.getElementById('kpi-files').textContent = fmtFull(last.files);
  document.getElementById('kpi-files-sub').textContent = `up from ${first.files} files`;
  document.getElementById('kpi-avg').textContent = '~' + fmt(avg);
  document.getElementById('kpi-avg-sub').textContent = `across ${data.length} weekly snapshots`;
}

// --- Charts ---
function mkTooltip() {
  return { backgroundColor:'#12121c', borderColor:'#2a2a3d', borderWidth:1, titleColor:'#e2e8f0', bodyColor:'#94a3b8' };
}

function buildDelta(data) { return data.map((d,i)=>i===0?0:Math.max(0,d.lines-data[i-1].lines)); }
function buildDensity(data) { return data.map(d=>d.files>0?+(d.lines/d.files).toFixed(1):0); }

function quarterOf(date) {
  const m = date.toLowerCase();
  if (m.startsWith('jan')||m.startsWith('feb')||m.startsWith('mar')) return 'Q1';
  if (m.startsWith('apr')||m.startsWith('may')||m.startsWith('jun')) return 'Q2';
  if (m.startsWith('jul')||m.startsWith('aug')||m.startsWith('sep')) return 'Q3';
  return 'Q4';
}

function getQuarterBreakdown(data) {
  const qmap = {};
  data.forEach((d,i)=>{ const q=quarterOf(d.date); const added=Math.max(0,d.lines-(i===0?0:data[i-1].lines)); qmap[q]=(qmap[q]||0)+added; });
  return ['Q3','Q4','Q1','Q2'].filter(q=>qmap[q]).map(q=>({q,v:qmap[q]}));
}

function initCharts(data) {
  Object.values(charts).forEach(c=>c.destroy());
  charts = {};
  const labels=data.map(d=>fmtDate(d.date)), lines=data.map(d=>d.lines), files=data.map(d=>d.files);
  const delta=buildDelta(data), density=buildDensity(data);
  const qColors=['rgba(167,139,250,.75)','rgba(96,165,250,.75)','rgba(52,211,153,.75)','rgba(251,146,60,.75)'];

  charts.trend = new Chart(document.getElementById('trendChart'), {
    type:'line',
    data:{labels,datasets:[
      {label:'Lines of Code',data:lines,borderColor:PURPLE,backgroundColor:'rgba(167,139,250,.1)',borderWidth:2.5,fill:true,tension:.35,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:PURPLE,yAxisID:'y'},
      {label:'File Count',data:files,borderColor:GREEN,backgroundColor:'transparent',borderWidth:2,borderDash:[5,3],fill:false,tension:.35,pointRadius:2,pointHoverRadius:5,pointBackgroundColor:GREEN,yAxisID:'y2'}
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{labels:{color:'#94a3b8',font:{size:12},usePointStyle:true}},tooltip:{...mkTooltip(),callbacks:{label:ctx=>ctx.datasetIndex===0?`  LOC: ${fmtFull(ctx.raw)}`:`  Files: ${ctx.raw}`}}},
      scales:{
        x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},
        y:{position:'left',ticks:{color:PURPLE,font:{size:11},callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID},title:{display:true,text:'Lines of Code',color:PURPLE,font:{size:11}}},
        y2:{position:'right',ticks:{color:GREEN,font:{size:11}},grid:{drawOnChartArea:false},title:{display:true,text:'Files',color:GREEN,font:{size:11}}}
      }}
  });

  const qb=getQuarterBreakdown(data);
  charts.donut = new Chart(document.getElementById('donutChart'), {
    type:'doughnut',
    data:{labels:qb.map(x=>x.q),datasets:[{data:qb.map(x=>x.v),backgroundColor:qb.map((_,i)=>qColors[i%4]),borderColor:'#1a1a26',borderWidth:3}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'62%',
      plugins:{legend:{position:'bottom',labels:{color:'#94a3b8',font:{size:12},usePointStyle:true,padding:12}},
        tooltip:{...mkTooltip(),callbacks:{label:ctx=>{const t=ctx.dataset.data.reduce((a,b)=>a+b,0);return `  ${fmtFull(ctx.raw)} lines (${((ctx.raw/t)*100).toFixed(0)}%)`;}}}}
    }
  });

  charts.delta = new Chart(document.getElementById('deltaChart'), {
    type:'bar',
    data:{labels,datasets:[{label:'Lines Added',data:delta,backgroundColor:delta.map(v=>v>3000?'rgba(251,146,60,.7)':'rgba(167,139,250,.65)'),borderColor:delta.map(v=>v>3000?ORANGE:PURPLE),borderWidth:1,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{...mkTooltip(),callbacks:{label:ctx=>`  +${fmtFull(ctx.raw)} lines`}}},
      scales:{x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},y:{ticks:{color:TICK,font:{size:11},callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID}}}}
  });

  charts.density = new Chart(document.getElementById('densityChart'), {
    type:'line',
    data:{labels,datasets:[{label:'LOC/File',data:density,borderColor:BLUE,backgroundColor:'rgba(96,165,250,.1)',borderWidth:2.5,fill:true,tension:.35,pointRadius:3,pointHoverRadius:6,pointBackgroundColor:BLUE}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{...mkTooltip(),callbacks:{label:ctx=>`  ${ctx.raw} lines/file`}}},
      scales:{x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},y:{ticks:{color:TICK,font:{size:11}},grid:{color:GRID},title:{display:true,text:'Lines per File',color:TICK,font:{size:11}}}}}
  });
}

function updateTable(data) {
  const max=Math.max(...data.map(d=>d.lines));
  document.getElementById('tbody').innerHTML = data.map((d,i)=>{
    const delta=i===0?0:d.lines-data[i-1].lines;
    const dh=delta>0?`<span class="pos">+${fmtFull(delta)}</span>`:delta<0?`<span class="neg">${fmtFull(delta)}</span>`:'—';
    const pct=((d.lines/max)*100).toFixed(1);
    const den=d.files>0?(d.lines/d.files).toFixed(1):'—';
    return `<tr><td>${fmtDate(d.date)}</td><td class="tr">${fmtFull(d.lines)}</td><td class="tr">${d.files}</td><td class="tr">${den}</td><td class="tr">${dh}</td><td><div class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:${pct}%"></div></div><span style="font-size:11px;color:#64748b">${pct}%</span></div></td></tr>`;
  }).join('');
}

function renderAll(data) {
  const filtered = filterByRange(data, activeMonths);
  updateKPIs(filtered);
  initCharts(filtered);
  updateTable(filtered);
}

// Boot
renderAll(currentData);
const updatedAt = '__UPDATED_AT__';
if (updatedAt) document.getElementById('last-updated').textContent = 'Updated ' + updatedAt;
document.getElementById('dash-title').textContent = '__REPO_NAME__ — LOC Dashboard';
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        return self.rfile.read(length)

    def do_GET(self):
        if self.path != '/':
            self.send_response(404); self.end_headers(); return
        with _lock:
            data = _cache['data']
            updated_at = _cache['updated_at'] or ''
            rpath = _cache['repo_path']
            rname = _cache['repo_name'] or repo_name(rpath)
        html = (HTML_TEMPLATE
                .replace('__INITIAL_DATA__', json.dumps(data))
                .replace('__UPDATED_AT__', updated_at)
                .replace('__REPO_PATH__', rpath)
                .replace('__REPO_NAME__', rname))
        body = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == '/api/set-repo':
            try:
                payload = json.loads(self.read_body())
                path = payload.get('path', '').strip()
            except Exception:
                self.send_json(400, {'error': 'Invalid JSON'}); return
            err = validate_git_repo(path)
            if err:
                self.send_json(400, {'error': err}); return
            with _lock:
                _cache['repo_path'] = path
                _cache['repo_name'] = repo_name(path)
                _cache['data'] = []
                _cache['updated_at'] = None
            self.send_json(200, {'ok': True})

        elif self.path == '/api/refresh':
            with _lock:
                if _cache['refreshing']:
                    self.send_json(409, {'error': 'Refresh already in progress'}); return
                _cache['refreshing'] = True
                path = _cache['repo_path']
            try:
                data, updated_at = do_refresh(path)
                with _lock:
                    rname = _cache['repo_name']
                self.send_json(200, {
                    'data': data,
                    'updated_at': updated_at,
                    'repo_path': path,
                    'repo_name': rname,
                })
            except Exception as e:
                with _lock:
                    _cache['refreshing'] = False
                self.send_json(500, {'error': str(e)})
        else:
            self.send_response(404); self.end_headers()


if __name__ == '__main__':
    err = validate_git_repo(DEFAULT_REPO)
    if err:
        print(f'Warning: default repo invalid — {err}')
        print('Open the dashboard and set a valid repo path.\n')
    else:
        _cache['repo_name'] = repo_name(DEFAULT_REPO)

    def initial_load():
        if not validate_git_repo(DEFAULT_REPO):
            do_refresh(DEFAULT_REPO)
        print(f'Dashboard ready → http://localhost:{PORT}\n', flush=True)

    print(f'Starting LOC dashboard on http://localhost:{PORT}')
    print('Loading initial data from git history (this takes ~30s)...\n')
    threading.Thread(target=initial_load, daemon=True).start()

    server = http.server.HTTPServer(('', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
