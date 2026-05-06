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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
  <style>
    :root {
      /* paper / surfaces */
      --paper-0: #EEEEEE;
      --paper-1: #E4E4E3;
      --paper-2: #D8D8D6;
      --paper-3: #C2C2C0;
      /* ink */
      --ink-0:   #0C0C0C;
      --ink-1:   #1C1C1B;
      --ink-2:   #303030;
      --ink-3:   #5A5A58;
      --ink-4:   #8A8A88;
      --ink-5:   #B4B4B2;
      /* accents */
      --lime:    #D4E635;
      --cobalt:  #1F47E6;
      --pink:    #FF4FA8;
      --kelly:   #3DB94A;
      /* layout */
      --gap: 16px;
      --ff-mono: 'JetBrains Mono', ui-monospace, 'Courier New', monospace;
      --ff-display: 'Space Grotesk', 'Helvetica Neue', Arial, sans-serif;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body {
      font-family: var(--ff-mono);
      background: var(--paper-0);
      color: var(--ink-0);
      padding: 24px;
      -webkit-font-smoothing: antialiased;
    }
    /* subtle paper noise overlay */
    body::before {
      content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 100;
      background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence baseFrequency='0.85'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.04 0'/></filter><rect width='200' height='200' filter='url(%23n)'/></svg>");
      mix-blend-mode: multiply;
    }
    ::selection { background: var(--lime); color: var(--ink-0); }
    .wrap { max-width: 1400px; margin: 0 auto; }

    /* ── MOTION ── */
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes caret-blink { 50% { opacity: 0; } }
    @keyframes pulse-dot { 0%,50%{opacity:1} 51%,100%{opacity:0.2} }

    /* ── SCROLLBAR ── */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: var(--paper-1); border-left: 1px solid var(--ink-0); }
    ::-webkit-scrollbar-thumb { background: var(--ink-0); }

    /* ── HEADER ── */
    header {
      border: 1px solid var(--ink-0);
      background: var(--paper-1);
      padding: 16px 20px;
      margin-bottom: var(--gap);
    }
    .header-top {
      display: flex; justify-content: space-between; align-items: flex-start;
      gap: 12px; flex-wrap: wrap;
    }
    .header-left {}
    .dash-code {
      font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--ink-4); margin-bottom: 4px;
    }
    #dash-title {
      font-family: var(--ff-display); font-size: 22px; font-weight: 700;
      letter-spacing: -0.02em; text-transform: uppercase; line-height: 1;
    }
    .header-sub {
      font-size: 10px; color: var(--ink-3); margin-top: 5px;
      letter-spacing: 0.05em; text-transform: uppercase;
    }
    .header-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    #last-updated { font-size: 10px; color: var(--ink-4); letter-spacing: 0.05em; text-transform: uppercase; }

    /* ── RANGE BAR ── */
    .range-bar { display: flex; }
    .range-btn {
      font-family: var(--ff-mono); font-size: 11px; font-weight: 500;
      letter-spacing: 0.1em; text-transform: uppercase;
      padding: 6px 11px; cursor: pointer;
      background: transparent; color: var(--ink-3);
      border: 1px solid var(--ink-0);
      margin-left: -1px; position: relative;
      transition: background 80ms linear, color 80ms linear;
    }
    .range-btn:first-child { margin-left: 0; }
    .range-btn:hover { background: var(--paper-2); color: var(--ink-0); }
    .range-btn.active {
      background: var(--ink-0); color: var(--paper-0); font-weight: 700; z-index: 1;
    }

    /* ── REPO ROW ── */
    .repo-row {
      display: flex; align-items: center; gap: 10px;
      margin-top: 14px; padding-top: 14px;
      border-top: 1px dotted var(--ink-4); flex-wrap: wrap;
    }
    .repo-label {
      font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--ink-4); white-space: nowrap;
    }
    .repo-path-display {
      font-family: var(--ff-mono); font-size: 12px; color: var(--ink-1);
      background: var(--paper-2); border: 1px solid var(--ink-0);
      padding: 5px 10px; flex: 1; min-width: 0;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      cursor: pointer; transition: background 80ms linear;
    }
    .repo-path-display:hover { background: var(--paper-3); }
    #repo-input {
      font-family: var(--ff-mono); font-size: 12px; color: var(--ink-0);
      background: var(--paper-0); border: 1px solid var(--ink-0);
      padding: 5px 10px; flex: 1; min-width: 200px; outline: none; display: none;
    }
    #repo-input:focus { outline: 2px solid var(--lime); outline-offset: -1px; }
    #repo-input.visible { display: block; }
    .repo-path-display.hidden { display: none; }

    /* ── BUTTONS ── */
    .btn {
      display: inline-flex; align-items: center; gap: 6px;
      font-family: var(--ff-mono); font-size: 11px; font-weight: 700;
      letter-spacing: 0.1em; text-transform: uppercase;
      padding: 7px 14px; cursor: pointer; border: 1px solid var(--ink-0);
      white-space: nowrap; position: relative;
      transition: transform 80ms linear, box-shadow 80ms linear, background 80ms linear;
    }
    .btn:hover   { transform: translate(1px,1px); }
    .btn:active  { transform: translate(2px,2px); }
    .btn:disabled { opacity: .4; cursor: not-allowed; transform: none; }
    .btn svg { width: 12px; height: 12px; flex-shrink: 0; }
    .btn-primary { background: var(--ink-0); color: var(--paper-0); }
    .btn-primary:hover:not(:disabled) { background: var(--ink-1); }
    .btn-lime { background: var(--lime); color: var(--ink-0); }
    .btn-lime:hover:not(:disabled) { background: #C8CF25; }
    .btn-ghost { background: transparent; color: var(--ink-3); }
    .btn-ghost:hover:not(:disabled) { background: var(--paper-2); color: var(--ink-0); }
    .spinning svg { animation: spin 1s linear infinite; }

    #repo-error {
      font-size: 10px; color: #C0392B; letter-spacing: 0.05em;
      text-transform: uppercase; display: none;
    }
    #repo-error.visible { display: block; }

    /* ── KPI ROW ── */
    .kpi-row {
      display: grid; grid-template-columns: repeat(4,1fr);
      gap: var(--gap); margin-bottom: var(--gap);
    }
    .kpi {
      background: var(--paper-1); border: 1px solid var(--ink-0); padding: 18px 20px;
    }
    .kpi-label {
      font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--ink-4); margin-bottom: 10px;
    }
    .kpi-value {
      font-family: var(--ff-display); font-size: 2.4rem; font-weight: 700;
      line-height: 1; letter-spacing: -0.02em; margin-bottom: 6px;
    }
    .kpi-sub { font-size: 10px; color: var(--ink-4); letter-spacing: 0.02em; }
    .c-lime   { color: var(--cobalt); }   /* LOC — cobalt */
    .c-growth { color: var(--kelly); }    /* growth — kelly green */
    .c-files  { color: var(--ink-0); }   /* files — ink */
    .c-avg    { color: var(--pink); }    /* avg — pink */

    /* ── CHART BOXES ── */
    .chart-row   { display: grid; grid-template-columns: 2fr 1fr; gap: var(--gap); margin-bottom: var(--gap); }
    .chart-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--gap); margin-bottom: var(--gap); }
    .chart-box {
      background: var(--paper-1); border: 1px solid var(--ink-0); padding: 18px 20px;
    }
    .chart-head {
      display: flex; justify-content: space-between; align-items: flex-start;
      margin-bottom: 14px;
    }
    .chart-box h3 {
      font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
      text-transform: uppercase; color: var(--ink-0);
    }
    .chart-code { font-size: 9px; color: var(--ink-5); letter-spacing: 0.15em; }
    .chart-box .csub {
      font-size: 10px; color: var(--ink-4); margin-top: 2px; letter-spacing: 0.04em;
    }
    canvas { max-height: 260px; }

    /* ── TABLE ── */
    .table-box {
      background: var(--paper-1); border: 1px solid var(--ink-0);
      padding: 18px 20px; margin-bottom: var(--gap); overflow-x: auto;
    }
    .table-head-row {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 14px;
    }
    .table-box h3 {
      font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
    }
    .table-code { font-size: 9px; color: var(--ink-5); letter-spacing: 0.15em; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th {
      text-align: left; padding: 7px 10px;
      border-bottom: 1px solid var(--ink-0);
      font-size: 9px; letter-spacing: 0.18em; text-transform: uppercase;
      color: var(--ink-3); font-weight: 500; white-space: nowrap;
      cursor: pointer; transition: color 80ms linear;
    }
    th:hover { color: var(--ink-0); }
    td {
      padding: 7px 10px;
      border-bottom: 1px dotted var(--ink-5);
      font-variant-numeric: tabular-nums;
      transition: background 80ms linear, color 80ms linear;
    }
    tr:last-child td { border-bottom: none; }
    tbody tr {
      box-shadow: inset 0 0 0 0 var(--ink-0);
      transition: box-shadow 80ms linear, background 80ms linear;
    }
    tbody tr:hover { background: var(--paper-2); box-shadow: inset 3px 0 0 0 var(--ink-0); }
    tbody tr:hover td { color: var(--ink-0); }
    .tr { text-align: right; }
    .pos { color: var(--kelly); font-weight: 700; }
    .neg { color: #C0392B; font-weight: 700; }
    .bar-cell { display: flex; align-items: center; gap: 8px; }
    .bar-bg { flex: 1; height: 3px; background: var(--paper-3); }
    .bar-fill { height: 100%; background: var(--ink-0); }
    .pct-label { font-size: 9px; color: var(--ink-4); letter-spacing: 0.05em; min-width: 32px; }

    /* ── FOOTER ── */
    footer {
      font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--ink-5); text-align: center; padding-top: 8px;
      border-top: 1px dotted var(--ink-5); margin-top: 8px;
    }

    /* ── RESPONSIVE ── */
    @media(max-width:900px) {
      .kpi-row { grid-template-columns: repeat(2,1fr); }
      .chart-row, .chart-row-2 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="header-top">
      <div class="header-left">
        <div class="dash-code">[LOC.01] &nbsp;·&nbsp; WEEKLY GIT SNAPSHOTS</div>
        <h1 id="dash-title">LOC Dashboard</h1>
        <div class="header-sub">TS &nbsp;·&nbsp; TSX &nbsp;·&nbsp; JS &nbsp;·&nbsp; JSX &nbsp;·&nbsp; CSS &nbsp;·&nbsp; SCSS</div>
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
        <button class="btn btn-lime" id="refresh-btn" onclick="triggerRefresh()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          Refresh
        </button>
      </div>
    </div>

    <div class="repo-row">
      <span class="repo-label">Repo</span>
      <div class="repo-path-display" id="repo-display" onclick="editRepo()" title="Click to change repo">__REPO_PATH__</div>
      <input id="repo-input" type="text" placeholder="/path/to/your/repo" onkeydown="repoKeydown(event)" />
      <button class="btn btn-primary" id="set-repo-btn" onclick="setRepo()" style="display:none">Set &amp; Refresh</button>
      <button class="btn btn-ghost" id="cancel-repo-btn" onclick="cancelEdit()" style="display:none">Cancel</button>
      <span id="repo-error"></span>
    </div>
  </header>

  <section class="kpi-row">
    <div class="kpi">
      <div class="kpi-label">Current LOC</div>
      <div class="kpi-value c-lime" id="kpi-loc">—</div>
      <div class="kpi-sub" id="kpi-loc-sub"></div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Total Growth</div>
      <div class="kpi-value c-growth" id="kpi-growth">—</div>
      <div class="kpi-sub" id="kpi-growth-sub"></div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Source Files</div>
      <div class="kpi-value c-files" id="kpi-files">—</div>
      <div class="kpi-sub" id="kpi-files-sub"></div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Avg LOC / Week</div>
      <div class="kpi-value c-avg" id="kpi-avg">—</div>
      <div class="kpi-sub" id="kpi-avg-sub"></div>
    </div>
  </section>

  <section class="chart-row">
    <div class="chart-box">
      <div class="chart-head">
        <div>
          <h3>Lines of Code &amp; File Count</h3>
          <div class="csub">LOC — left axis &nbsp;·&nbsp; files — right axis (dashed)</div>
        </div>
        <span class="chart-code">[CHT.01]</span>
      </div>
      <canvas id="trendChart"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-head">
        <div>
          <h3>Growth by Quarter</h3>
          <div class="csub">LOC added per quarter</div>
        </div>
        <span class="chart-code">[CHT.02]</span>
      </div>
      <canvas id="donutChart"></canvas>
    </div>
  </section>

  <section class="chart-row-2">
    <div class="chart-box">
      <div class="chart-head">
        <div>
          <h3>Weekly LOC Added</h3>
          <div class="csub">Net lines added per week</div>
        </div>
        <span class="chart-code">[CHT.03]</span>
      </div>
      <canvas id="deltaChart"></canvas>
    </div>
    <div class="chart-box">
      <div class="chart-head">
        <div>
          <h3>LOC per File</h3>
          <div class="csub">Average lines per source file</div>
        </div>
        <span class="chart-code">[CHT.04]</span>
      </div>
      <canvas id="densityChart"></canvas>
    </div>
  </section>

  <section class="table-box">
    <div class="table-head-row">
      <h3>Weekly Snapshot Data</h3>
      <span class="table-code">[TBL.01]</span>
    </div>
    <table>
      <thead><tr>
        <th>Date</th>
        <th class="tr">Lines of Code</th>
        <th class="tr">Files</th>
        <th class="tr">LOC / File</th>
        <th class="tr">Week Delta</th>
        <th style="min-width:140px">Progress</th>
      </tr></thead>
      <tbody id="tbody"></tbody>
    </table>
  </section>

  <footer>loc-dashboard &nbsp;·&nbsp; loc_server.py &nbsp;·&nbsp; [v2]</footer>
</div>

<script>
const COBALT='#1F47E6', KELLY='#3DB94A', PINK='#FF4FA8', LIME='#D4E635', INK='#0C0C0C';
const GRID='rgba(194,194,192,0.6)', TICK='#8A8A88';

let charts = {};
let currentData = __INITIAL_DATA__;
let currentRepo = '__REPO_PATH__';
let activeMonths = 12;

function fmt(n) { return n >= 1000 ? (n/1000).toFixed(1)+'k' : String(n); }
function fmtFull(n) { return n.toLocaleString(); }

function fmtDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  const yr = String(d.getFullYear()).slice(2);
  return d.toLocaleString('en', {month:'short'}) + ' ' + String(d.getDate()).padStart(2,'0') + " '" + yr;
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
  el.className = msg ? 'visible' : '';
  el.id = 'repo-error';
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
    if (!res.ok) { setRepoError(json.error || 'Invalid repo path'); return; }
    currentRepo = path;
    document.getElementById('repo-display').textContent = path;
    cancelEdit();
    await triggerRefresh();
  } catch(e) {
    setRepoError('Request failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Set &amp; Refresh';
  }
}

async function triggerRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.classList.add('spinning');
  btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Counting…`;
  try {
    const res = await fetch('/api/refresh', { method: 'POST' });
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || 'Refresh failed');
    currentData = json.data;
    currentRepo = json.repo_path;
    document.getElementById('repo-display').textContent = currentRepo;
    document.getElementById('dash-title').textContent = json.repo_name.toUpperCase() + ' — LOC';
    renderAll(currentData);
    document.getElementById('last-updated').textContent = 'Updated ' + json.updated_at;
  } catch(e) {
    alert('Refresh failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.classList.remove('spinning');
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"/><path d="M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg> Refresh`;
  }
}

function updateKPIs(data) {
  if (!data.length) return;
  const last = data[data.length-1], first = data[0];
  const growth = last.lines - first.lines;
  const avg = Math.round(growth / data.length);
  document.getElementById('kpi-loc').textContent = fmt(last.lines);
  document.getElementById('kpi-loc-sub').textContent = 'as of ' + fmtDate(last.date);
  document.getElementById('kpi-growth').textContent = '+' + fmtFull(growth);
  document.getElementById('kpi-growth-sub').textContent = 'from ' + fmtFull(first.lines) + ' at launch';
  document.getElementById('kpi-files').textContent = fmtFull(last.files);
  document.getElementById('kpi-files-sub').textContent = 'up from ' + first.files + ' files';
  document.getElementById('kpi-avg').textContent = '~' + fmt(avg);
  document.getElementById('kpi-avg-sub').textContent = 'across ' + data.length + ' weekly snapshots';
}

function mkTooltip() {
  return {
    backgroundColor: '#1C1C1B', borderColor: '#303030', borderWidth: 1,
    titleColor: '#EEEEEE', bodyColor: '#8A8A88',
    titleFont: {family:'JetBrains Mono, monospace', size:11},
    bodyFont: {family:'JetBrains Mono, monospace', size:11},
    padding: 10, cornerRadius: 0,
  };
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
  return ['Q1','Q2','Q3','Q4'].filter(q=>qmap[q]).map(q=>({q,v:qmap[q]}));
}

function initCharts(data) {
  Object.values(charts).forEach(c=>c.destroy());
  charts = {};
  const labels=data.map(d=>fmtDate(d.date)), lines=data.map(d=>d.lines), files=data.map(d=>d.files);
  const delta=buildDelta(data), density=buildDensity(data);
  const monoFont = {family:'JetBrains Mono, monospace', size:10};
  const qColors=[COBALT, KELLY, PINK, LIME];

  charts.trend = new Chart(document.getElementById('trendChart'), {
    type:'line',
    data:{labels,datasets:[
      {label:'Lines of Code',data:lines,borderColor:COBALT,backgroundColor:'rgba(31,71,230,0.08)',borderWidth:2,fill:true,tension:.3,pointRadius:2,pointHoverRadius:5,pointBackgroundColor:COBALT,yAxisID:'y'},
      {label:'File Count',data:files,borderColor:KELLY,backgroundColor:'transparent',borderWidth:1.5,borderDash:[4,3],fill:false,tension:.3,pointRadius:1,pointHoverRadius:4,pointBackgroundColor:KELLY,yAxisID:'y2'}
    ]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{labels:{color:TICK,font:monoFont,usePointStyle:true,pointStyleWidth:8}},
        tooltip:{...mkTooltip(),callbacks:{label:ctx=>ctx.datasetIndex===0?`  LOC: ${fmtFull(ctx.raw)}`:`  Files: ${ctx.raw}`}}
      },
      scales:{
        x:{ticks:{color:TICK,font:monoFont,maxRotation:45},grid:{color:GRID}},
        y:{position:'left',ticks:{color:COBALT,font:monoFont,callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID},title:{display:true,text:'LOC',color:COBALT,font:monoFont}},
        y2:{position:'right',ticks:{color:KELLY,font:monoFont},grid:{drawOnChartArea:false},title:{display:true,text:'Files',color:KELLY,font:monoFont}}
      }}
  });

  const qb=getQuarterBreakdown(data);
  charts.donut = new Chart(document.getElementById('donutChart'), {
    type:'doughnut',
    data:{labels:qb.map(x=>x.q),datasets:[{data:qb.map(x=>x.v),backgroundColor:qb.map((_,i)=>qColors[i%4]),borderColor:'#E4E4E3',borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'58%',
      plugins:{
        legend:{position:'bottom',labels:{color:TICK,font:monoFont,usePointStyle:true,padding:14}},
        tooltip:{...mkTooltip(),callbacks:{label:ctx=>{const t=ctx.dataset.data.reduce((a,b)=>a+b,0);return `  ${fmtFull(ctx.raw)} (${((ctx.raw/t)*100).toFixed(0)}%)`;}}}}
    }
  });

  charts.delta = new Chart(document.getElementById('deltaChart'), {
    type:'bar',
    data:{labels,datasets:[{label:'Lines Added',data:delta,
      backgroundColor:delta.map(v=>v>3000?'rgba(255,79,168,0.7)':'rgba(31,71,230,0.55)'),
      borderColor:delta.map(v=>v>3000?PINK:COBALT),
      borderWidth:1,borderRadius:0}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{...mkTooltip(),callbacks:{label:ctx=>`  +${fmtFull(ctx.raw)} lines`}}},
      scales:{x:{ticks:{color:TICK,font:monoFont,maxRotation:45},grid:{color:GRID}},y:{ticks:{color:TICK,font:monoFont,callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID}}}}
  });

  charts.density = new Chart(document.getElementById('densityChart'), {
    type:'line',
    data:{labels,datasets:[{label:'LOC/File',data:density,borderColor:INK,backgroundColor:'rgba(12,12,12,0.06)',borderWidth:2,fill:true,tension:.3,pointRadius:2,pointHoverRadius:5,pointBackgroundColor:INK}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},tooltip:{...mkTooltip(),callbacks:{label:ctx=>`  ${ctx.raw} lines/file`}}},
      scales:{x:{ticks:{color:TICK,font:monoFont,maxRotation:45},grid:{color:GRID}},y:{ticks:{color:TICK,font:monoFont},grid:{color:GRID},title:{display:true,text:'Lines / File',color:TICK,font:monoFont}}}}
  });
}

function updateTable(data) {
  const max=Math.max(...data.map(d=>d.lines));
  document.getElementById('tbody').innerHTML = data.map((d,i)=>{
    const delta=i===0?0:d.lines-data[i-1].lines;
    const dh=delta>0?`<span class="pos">+${fmtFull(delta)}</span>`:delta<0?`<span class="neg">${fmtFull(delta)}</span>`:'—';
    const pct=((d.lines/max)*100).toFixed(1);
    const den=d.files>0?(d.lines/d.files).toFixed(1):'—';
    return `<tr>
      <td>${fmtDate(d.date)}</td>
      <td class="tr">${fmtFull(d.lines)}</td>
      <td class="tr">${d.files}</td>
      <td class="tr">${den}</td>
      <td class="tr">${dh}</td>
      <td><div class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:${pct}%"></div></div><span class="pct-label">${pct}%</span></div></td>
    </tr>`;
  }).join('');
}

function renderAll(data) {
  const filtered = filterByRange(data, activeMonths);
  updateKPIs(filtered);
  initCharts(filtered);
  updateTable(filtered);
}

renderAll(currentData);
const updatedAt = '__UPDATED_AT__';
if (updatedAt) document.getElementById('last-updated').textContent = 'Updated ' + updatedAt;
const repoName = '__REPO_NAME__';
if (repoName) document.getElementById('dash-title').textContent = repoName.toUpperCase() + ' — LOC';
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
