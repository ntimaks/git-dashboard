# loc-dashboard

A local dashboard that tracks lines of code growth over time for a git repository, using weekly snapshots from git history.

## What it does

- Counts lines of code across weekly git snapshots (TS, TSX, JS, JSX, CSS, SCSS)
- Serves an interactive dashboard at `http://localhost:8765`
- Includes a **Refresh Data** button that re-runs the git count live (~30s)

## Charts

- Lines of code + file count over time (dual axis)
- LOC added per quarter (donut)
- Weekly lines added (bar)
- Average lines per file over time

## Setup

1. Open `loc_server.py` and update `REPO_PATH` to point to your git repository:

```python
REPO_PATH = "/path/to/your/repo"
```

2. Run the server:

```bash
python3 loc_server.py
```

3. Open your browser at [http://localhost:8765](http://localhost:8765)

The initial data load takes ~30 seconds. The dashboard will show data once it's ready. Hit **Refresh Data** anytime to re-count from the latest git history.

## Requirements

- Python 3 (standard library only, no installs needed)
- Git available in your PATH
