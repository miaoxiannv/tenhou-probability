# SheetPilot Studio

> Natural-language table + chart workspace for fast data exploration.

**English** | [简体中文](./README_CN.md)

---

## Overview

SheetPilot Studio is a three-pane data visualization workspace:

- Left: Excel-like table surface (upload, preview, table operations)
- Middle: chat agent with explicit modes (`auto`, `chat`, `plot`, `table`)
- Right: PlotSpec-first chart panel (spec editing, stats overlay, PNG/PDF export)

Backend is Spec-first: it returns structured `plot_spec` + `plot_payload`, and frontend renders directly from payload.

## Why This Project

- Fast workflow: upload -> chat -> plot -> export
- Predictable behavior: explicit chat modes + schema validation
- Stable results: same request can reuse cached plot spec in a session
- Resilience: model planning fallback to rule engine when needed

## Core Features

- Session workflow: `POST /api/session`
- Upload: `.csv/.xlsx/.xls` (30MB max, 1,000,000 rows max)
- Chat table controls:
  - load local file
  - preview/filter/sort/reset/clear
  - cell edits (`B1`, row/column index, row ranges)
  - group-wise numeric clipping
  - undo/redo + named snapshots
- Chart types:
  - `scatter`, `line`, `bar`, `hist`, `box`, `violin`, `heatmap`, `composed`
- Advanced composition:
  - `layers` (`scatter/line/bar/hist/boxplot/violin/regression`)
  - `facet`
  - `stats_overlay`
- Exports:
  - CSV: `POST /api/export/csv`
  - PNG: `POST /api/export/png`
  - PDF: `POST /api/export/pdf`
- Session observability:
  - state: `GET /api/session/state`
  - history: `GET /api/session/history`

## Chat Modes (`/api/chat`)

- `auto` (default): route between chat/table/plot automatically
- `chat`: conversation only (no table mutation, no new plot generation)
- `plot`: force plotting pipeline
- `table`: table commands only

## Quick Start

```bash
cd /home/zhang/tenhou-probability

python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

npm run frontend:install
npm run frontend:build

cp .env.example .env
./scripts/run_server.sh
```

Open: `http://127.0.0.1:8888`

## Development

```bash
# backend
npm run dev:py

# frontend
npm run frontend:dev
```

Frontend dev server: `http://127.0.0.1:5173`

## API Summary

- `GET /health`
- `POST /api/session`
- `POST /api/upload?session_id=...`
- `POST /api/chat`
- `POST /api/plot/spec`
- `POST /api/stats`
- `GET /api/session/state`
- `GET /api/session/history`
- `POST /api/export/csv`
- `POST /api/export/png`
- `POST /api/export/pdf`

## Project Structure

```text
.
├── backend/
│   ├── main.py
│   ├── spec_utils.py
│   ├── plot_payload.py
│   ├── stats_engine.py
│   ├── plot_engine.py
│   ├── llm_client.py
│   └── tests/
├── frontend/
│   ├── src/App.jsx
│   ├── src/components/
│   ├── src/api/client.js
│   └── package.json
├── scripts/
│   ├── run_server.sh
│   └── stop_server.sh
├── README.md
├── README_EN.md
└── README_CN.md
```

## Documentation

- Chinese docs: [README_CN.md](./README_CN.md)
- Extended English docs: [README_EN.md](./README_EN.md)

## Security Notes

- API keys are loaded from environment variables only
- Local file loading in chat is restricted to allowed roots
- PlotSpec is validated server-side before rendering
- Upload file type is whitelist-based (`csv/xlsx/xls`)
