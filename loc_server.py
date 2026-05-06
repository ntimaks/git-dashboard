#!/usr/bin/env python3
"""
LOC dashboard server for hackmotion-web-frontend.
Run from anywhere: python3 loc_server.py
Then open:        http://localhost:8765
"""
import http.server
import json
import subprocess
import threading
import os
import sys
from datetime import datetime

REPO_PATH = "/Users/nikolasstimaks/Local Sites/hm-local/app/hackmotion-web-frontend"
PORT = 8765
EXTS = ('.ts', '.tsx', '.js', '.jsx', '.css', '.scss')
EXCLUDE = ('node_modules', '/.next/', '/dist/')

_cache = {'data': [], 'updated_at': None, 'refreshing': False}
_lock = threading.Lock()


def get_weekly_commits():
    r = subprocess.run(
        ['git', 'log', '--reverse', '--format=%H %ad', '--date=format:%Y-%W'],
        capture_output=True, text=True, cwd=REPO_PATH
    )
    seen = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hash_, week = parts
            if week not in seen:
                seen[week] = hash_
    return list(seen.values())


def count_lines_at(hash_):
    r = subprocess.run(
        ['git', 'ls-tree', '-r', '--name-only', hash_],
        capture_output=True, text=True, cwd=REPO_PATH
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
        input=blob_specs, capture_output=True, text=True, errors='replace',
        cwd=REPO_PATH
    )
    return cat.stdout.count('\n'), len(files)


def get_date_for_commit(hash_):
    r = subprocess.run(
        ['git', 'log', '-1', '--format=%ad', '--date=format:%b %d', hash_],
        capture_output=True, text=True, cwd=REPO_PATH
    )
    return r.stdout.strip()


def do_refresh():
    print('Counting LOC across weekly commits...', flush=True)
    commits = get_weekly_commits()
    results = []
    for i, hash_ in enumerate(commits):
        lines, files = count_lines_at(hash_)
        if lines == 0:
            continue
        date = get_date_for_commit(hash_)
        results.append({'date': date, 'lines': lines, 'files': files})
        print(f'  [{i+1}/{len(commits)}] {date}: {lines:,} lines', flush=True)

    updated_at = datetime.now().strftime('%b %d, %Y %H:%M')
    with _lock:
        _cache['data'] = results
        _cache['updated_at'] = updated_at
        _cache['refreshing'] = False
    print(f'Done. {len(results)} snapshots.', flush=True)
    return results, updated_at


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>hackmotion-web-frontend — LOC Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1" integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" crossorigin="anonymous"></script>
  <style>
    :root {
      --bg: #0f0f13; --card: #1a1a26; --header: #12121c;
      --border: #2a2a3d; --t1: #e2e8f0; --t2: #64748b; --t3: #3f4a5e;
      --purple: #a78bfa; --green: #34d399; --blue: #60a5fa; --orange: #fb923c;
      --red: #f87171; --gap: 16px; --r: 10px;
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:var(--bg); color:var(--t1); padding:24px; }
    .wrap { max-width:1400px; margin:0 auto; }

    /* header */
    header { background:var(--header); border:1px solid var(--border); border-radius:var(--r); padding:18px 24px; margin-bottom:var(--gap); display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }
    header h1 { font-size:16px; font-weight:600; }
    header .sub { font-size:11px; color:var(--t2); margin-top:2px; }
    .header-right { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
    #last-updated { font-size:11px; color:var(--t2); }

    /* refresh button */
    #refresh-btn {
      display:flex; align-items:center; gap:7px;
      background:rgba(167,139,250,0.12); color:var(--purple);
      border:1px solid rgba(167,139,250,0.3); border-radius:6px;
      padding:7px 14px; font-size:13px; font-weight:500; cursor:pointer;
      transition:background 0.15s,opacity 0.15s;
    }
    #refresh-btn:hover { background:rgba(167,139,250,0.22); }
    #refresh-btn:disabled { opacity:0.5; cursor:not-allowed; }
    #refresh-btn svg { width:14px; height:14px; flex-shrink:0; }
    #refresh-btn.spinning svg { animation:spin 1s linear infinite; }
    @keyframes spin { to { transform:rotate(360deg); } }

    /* kpi */
    .kpi-row { display:grid; grid-template-columns:repeat(4,1fr); gap:var(--gap); margin-bottom:var(--gap); }
    .kpi { background:var(--card); border:1px solid var(--border); border-radius:var(--r); padding:18px 20px; }
    .kpi-label { font-size:11px; color:var(--t2); text-transform:uppercase; letter-spacing:.07em; margin-bottom:7px; }
    .kpi-value { font-size:1.9rem; font-weight:700; line-height:1; margin-bottom:5px; }
    .kpi-sub { font-size:11px; color:var(--t2); }
    .c-purple { color:var(--purple); } .c-green { color:var(--green); } .c-blue { color:var(--blue); } .c-orange { color:var(--orange); }

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
    .pos { color:var(--green); } .neg { color:var(--red); }
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
    <div>
      <h1>hackmotion-web-frontend &mdash; Lines of Code</h1>
      <div class="sub">Weekly git snapshots &nbsp;·&nbsp; TS, TSX, JS, JSX, CSS, SCSS</div>
    </div>
    <div class="header-right">
      <span id="last-updated"></span>
      <button id="refresh-btn" onclick="refresh()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M23 4v6h-6"/><path d="M1 20v-6h6"/>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
        </svg>
        Refresh Data
      </button>
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

  <footer>hackmotion-web-frontend git history &nbsp;·&nbsp; served by loc_server.py</footer>
</div>

<script>
const PURPLE='#a78bfa', GREEN='#34d399', BLUE='#60a5fa', ORANGE='#fb923c';
const GRID='rgba(42,42,61,0.8)', TICK='#4a5568';

let charts = {};
let currentData = __INITIAL_DATA__;

function fmt(n) { return n >= 1000 ? (n/1000).toFixed(1)+'k' : String(n); }
function fmtFull(n) { return n.toLocaleString(); }

function buildDelta(data) {
  return data.map((d,i) => i===0 ? 0 : Math.max(0, d.lines - data[i-1].lines));
}

function buildDensity(data) {
  return data.map(d => d.files > 0 ? +(d.lines/d.files).toFixed(1) : 0);
}

function quarterOf(date) {
  const m = date.toLowerCase();
  if (m.startsWith('jan')||m.startsWith('feb')||m.startsWith('mar')) return 'Q1';
  if (m.startsWith('apr')||m.startsWith('may')||m.startsWith('jun')) return 'Q2';
  if (m.startsWith('jul')||m.startsWith('aug')||m.startsWith('sep')) return 'Q3';
  return 'Q4';
}

function getQuarterBreakdown(data) {
  const qmap = {};
  for (let i=0; i<data.length; i++) {
    const q = quarterOf(data[i].date);
    const prev = i===0 ? 0 : data[i-1].lines;
    const added = Math.max(0, data[i].lines - prev);
    qmap[q] = (qmap[q]||0) + added;
  }
  const order = ['Q3','Q4','Q1','Q2'];
  return order.filter(q => qmap[q]).map(q => ({q, v: qmap[q]}));
}

function updateKPIs(data) {
  if (!data.length) return;
  const last = data[data.length-1];
  const first = data[0];
  const growth = last.lines - first.lines;
  const weeks = data.length;
  const avgPerWeek = Math.round(growth / weeks);

  document.getElementById('kpi-loc').textContent = fmt(last.lines);
  document.getElementById('kpi-loc-sub').textContent = 'as of ' + last.date;
  document.getElementById('kpi-growth').textContent = '+' + fmtFull(growth);
  document.getElementById('kpi-growth-sub').textContent = `from ${first.lines} lines at launch`;
  document.getElementById('kpi-files').textContent = fmtFull(last.files);
  document.getElementById('kpi-files-sub').textContent = `up from ${first.files} files`;
  document.getElementById('kpi-avg').textContent = '~'+fmt(avgPerWeek);
  document.getElementById('kpi-avg-sub').textContent = `across ${weeks} weekly snapshots`;
}

function mkTooltip() {
  return {
    backgroundColor:'#12121c', borderColor:'#2a2a3d', borderWidth:1,
    titleColor:'#e2e8f0', bodyColor:'#94a3b8'
  };
}

function initCharts(data) {
  const labels = data.map(d=>d.date);
  const lines  = data.map(d=>d.lines);
  const files  = data.map(d=>d.files);
  const delta  = buildDelta(data);
  const density= buildDensity(data);

  // destroy existing
  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  // Trend
  charts.trend = new Chart(document.getElementById('trendChart'), {
    type:'line',
    data:{ labels, datasets:[
      { label:'Lines of Code', data:lines, borderColor:PURPLE, backgroundColor:'rgba(167,139,250,.1)', borderWidth:2.5, fill:true, tension:.35, pointRadius:3, pointHoverRadius:6, pointBackgroundColor:PURPLE, yAxisID:'y' },
      { label:'File Count', data:files, borderColor:GREEN, backgroundColor:'transparent', borderWidth:2, borderDash:[5,3], fill:false, tension:.35, pointRadius:2, pointHoverRadius:5, pointBackgroundColor:GREEN, yAxisID:'y2' }
    ]},
    options:{ responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
      plugins:{ legend:{labels:{color:'#94a3b8',font:{size:12},usePointStyle:true}}, tooltip:{...mkTooltip(), callbacks:{label:ctx=>ctx.datasetIndex===0?`  LOC: ${fmtFull(ctx.raw)}`:`  Files: ${ctx.raw}`}} },
      scales:{
        x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},
        y:{position:'left',ticks:{color:PURPLE,font:{size:11},callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID},title:{display:true,text:'Lines of Code',color:PURPLE,font:{size:11}}},
        y2:{position:'right',ticks:{color:GREEN,font:{size:11}},grid:{drawOnChartArea:false},title:{display:true,text:'Files',color:GREEN,font:{size:11}}}
      }
    }
  });

  // Donut
  const qb = getQuarterBreakdown(data);
  const qColors = ['rgba(167,139,250,.75)','rgba(96,165,250,.75)','rgba(52,211,153,.75)','rgba(251,146,60,.75)'];
  charts.donut = new Chart(document.getElementById('donutChart'), {
    type:'doughnut',
    data:{ labels:qb.map(x=>x.q), datasets:[{ data:qb.map(x=>x.v), backgroundColor:qb.map((_,i)=>qColors[i%4]), borderColor:'#1a1a26', borderWidth:3 }] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'62%',
      plugins:{ legend:{position:'bottom',labels:{color:'#94a3b8',font:{size:12},usePointStyle:true,padding:12}},
        tooltip:{...mkTooltip(), callbacks:{label:ctx=>{ const t=ctx.dataset.data.reduce((a,b)=>a+b,0); return `  ${fmtFull(ctx.raw)} lines (${((ctx.raw/t)*100).toFixed(0)}%)`; }}}
      }
    }
  });

  // Delta
  charts.delta = new Chart(document.getElementById('deltaChart'), {
    type:'bar',
    data:{ labels, datasets:[{ label:'Lines Added', data:delta,
      backgroundColor:delta.map(v=>v>3000?'rgba(251,146,60,.7)':'rgba(167,139,250,.65)'),
      borderColor:delta.map(v=>v>3000?ORANGE:PURPLE), borderWidth:1, borderRadius:3
    }]},
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{...mkTooltip(), callbacks:{label:ctx=>`  +${fmtFull(ctx.raw)} lines`}} },
      scales:{
        x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},
        y:{ticks:{color:TICK,font:{size:11},callback:v=>v>=1000?(v/1000).toFixed(0)+'k':v},grid:{color:GRID}}
      }
    }
  });

  // Density
  charts.density = new Chart(document.getElementById('densityChart'), {
    type:'line',
    data:{ labels, datasets:[{ label:'LOC/File', data:density, borderColor:BLUE, backgroundColor:'rgba(96,165,250,.1)', borderWidth:2.5, fill:true, tension:.35, pointRadius:3, pointHoverRadius:6, pointBackgroundColor:BLUE }] },
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false}, tooltip:{...mkTooltip(), callbacks:{label:ctx=>`  ${ctx.raw} lines/file`}} },
      scales:{
        x:{ticks:{color:TICK,font:{size:10},maxRotation:45},grid:{color:GRID}},
        y:{ticks:{color:TICK,font:{size:11}},grid:{color:GRID},title:{display:true,text:'Lines per File',color:TICK,font:{size:11}}}
      }
    }
  });
}

function updateTable(data) {
  const max = Math.max(...data.map(d=>d.lines));
  document.getElementById('tbody').innerHTML = data.map((d,i)=>{
    const delta = i===0 ? 0 : d.lines - data[i-1].lines;
    const deltaHtml = delta>0 ? `<span class="pos">+${fmtFull(delta)}</span>`
                    : delta<0 ? `<span class="neg">${fmtFull(delta)}</span>` : '—';
    const pct = ((d.lines/max)*100).toFixed(1);
    const density = d.files>0 ? (d.lines/d.files).toFixed(1) : '—';
    return `<tr>
      <td>${d.date}</td>
      <td class="tr">${fmtFull(d.lines)}</td>
      <td class="tr">${d.files}</td>
      <td class="tr">${density}</td>
      <td class="tr">${deltaHtml}</td>
      <td><div class="bar-cell"><div class="bar-bg"><div class="bar-fill" style="width:${pct}%"></div></div><span style="font-size:11px;color:#64748b">${pct}%</span></div></td>
    </tr>`;
  }).join('');
}

function renderAll(data) {
  updateKPIs(data);
  initCharts(data);
  updateTable(data);
}

async function refresh() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.classList.add('spinning');
  btn.querySelector('span') && (btn.querySelector('span').textContent = 'Refreshing…');
  // replace button text node
  for (const node of btn.childNodes) {
    if (node.nodeType === 3) { node.textContent = ' Refreshing…'; break; }
  }

  try {
    const res = await fetch('/api/refresh', { method:'POST' });
    const json = await res.json();
    currentData = json.data;
    renderAll(currentData);
    document.getElementById('last-updated').textContent = 'Updated ' + json.updated_at;
  } catch(e) {
    alert('Refresh failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.classList.remove('spinning');
    for (const node of btn.childNodes) {
      if (node.nodeType === 3) { node.textContent = ' Refresh Data'; break; }
    }
  }
}

// Initial render
renderAll(currentData);
const updatedAt = '__UPDATED_AT__';
if (updatedAt) document.getElementById('last-updated').textContent = 'Updated ' + updatedAt;
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress per-request noise

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/':
            with _lock:
                data = _cache['data']
                updated_at = _cache['updated_at'] or ''
            html = HTML_TEMPLATE \
                .replace('__INITIAL_DATA__', json.dumps(data)) \
                .replace('__UPDATED_AT__', updated_at)
            body = html.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/refresh':
            with _lock:
                if _cache['refreshing']:
                    self.send_json(409, {'error': 'refresh already in progress'})
                    return
                _cache['refreshing'] = True
            try:
                data, updated_at = do_refresh()
                self.send_json(200, {'data': data, 'updated_at': updated_at})
            except Exception as e:
                with _lock:
                    _cache['refreshing'] = False
                self.send_json(500, {'error': str(e)})
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    # Run an initial data load in the background so the dashboard has data on first open
    def initial_load():
        do_refresh()
        print(f'\nDashboard ready → http://localhost:{PORT}\n', flush=True)

    print(f'Starting LOC dashboard server on http://localhost:{PORT}')
    print('Loading initial data from git history (this takes ~30s)...\n')
    threading.Thread(target=initial_load, daemon=True).start()

    server = http.server.HTTPServer(('', PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
