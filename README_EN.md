# SheetPilot Studio

[English](./README.md) | [简体中文](./README_CN.md)

A three-pane natural-language data visualization workspace.

- Left: Excel-like table surface (upload, preview, table ops)
- Middle: chat agent with explicit modes (`auto`, `chat`, `plot`, `table`)
- Right: PlotSpec-first chart panel (spec editing, stats overlay, PNG/PDF export)

## Read This First

Recommended onboarding order:

1. Read "Core Request Paths" and "Developer Entry Map" in this README.
2. Open `backend/main.py` (routing + orchestration + session state).
3. Open `frontend/src/App.jsx` and `frontend/src/components/PlotCanvas.jsx`.

If you just want to run it quickly, jump to "Quick Start".

## Overview

Backend is Spec-first: it returns structured `plot_spec` + `plot_payload`; frontend renders from payload only (no arbitrary plotting script execution on client).

Covered workflow:

- CSV/Excel upload
- chat-driven table operations (filter/sort/edit/undo/redo/snapshots)
- chat-driven plotting (LLM-first with rule fallback)
- layered charts + stats overlay
- session observability
- CSV/PNG/PDF export

When model output is unavailable or invalid, backend falls back to a rule engine and attempts repair so the flow remains usable.

## Core Features

- Session workflow: `POST /api/session`
- Upload: `.csv/.xlsx/.xls` (30MB max, 1,000,000 rows max)
- Chat table controls:
  - load local file
  - preview/filter/sort/reset/clear
  - cell updates (`B1`, row/column index, row ranges)
  - group-wise numeric clipping
  - undo/redo
  - named snapshots
- Chart types:
  - `scatter`, `line`, `bar`, `hist`, `box`, `violin`, `heatmap`, `composed`
- Advanced composition:
  - `layers` (`scatter/line/bar/hist/boxplot/violin/regression`)
  - `facet`
  - `stats_overlay`
- Stable plot policy:
  - repeated same plotting request in one session can reuse cached spec
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
- `table`: table command only

## Core Request Paths

### A. Table command path

1. Message enters `/api/chat`
2. Parser recognizes table command
3. Session state updates (`df/view_df/undo/redo/snapshots`)
4. Returns updated `table_state` and, when possible, refreshed current plot context

### B. Plot intent path

1. Message enters `/api/chat`
2. Strategy routing:
   - cache hit -> spec reuse
   - template hit -> rule template
   - explicit edit -> incremental rule update
   - otherwise model planning, fallback to rules on error
3. Validate `plot_spec` against schema/columns
4. Build `plot_payload` + optional stats
5. Return metadata (`execution_strategy`, `fallback_reason`, `mode_used`, `intent`)

## Chat Response Fields (Important)

- `summary`: user-facing concise summary
- `plot_spec`: validated canonical spec
- `plot_payload`: frontend rendering payload
- `stats`: statistical result (nullable)
- `execution_strategy`: route taken (e.g. `model_primary`, `rule_edit`, `cache_reuse`)
- `fallback_reason`: reason for fallback (e.g. `missing_api_key`, `model_api_or_parse_error`)
- `mode_used`: actual mode used
- `intent`: backend intent classification (`chat/table/plot`)
- `thinking`: truncated execution trace

## Developer Entry Map

```text
backend/main.py
  ├─ Routes: /api/chat /api/upload /api/export/*
  ├─ Session state: undo/redo/snapshots/history/cache
  ├─ Table command parsing/execution
  └─ Plot orchestration: model -> fallback -> validation -> payload

backend/spec_utils.py
  └─ PlotSpec schema/validation/column resolution/filter logic

backend/plot_payload.py
  └─ DataFrame + PlotSpec -> frontend payload (layers/facets/stats overlay)

backend/stats_engine.py
  └─ Welch t-test / ANOVA / permutation fallback

frontend/src/App.jsx
  └─ Three-pane state management and API wiring

frontend/src/components/PlotCanvas.jsx
  └─ Plotly trace/layout building (regression/facet/dual-axis)
```

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

## Chat Command Examples

- Load file:
  - `加载文件 /home/zhang/data.csv`
  - `load file /home/zhang/data.csv`
- Cell update:
  - `把第一行第二列的值改成2`
  - `set cell B1 to 8`
- Range update:
  - `把第1到10行第2列的值改成0`
  - `set rows 1-10 col 2 to 0`
- Group clip:
  - `把Group中的Control组的所有Expression的范围更改为5-7`
  - `clip Expression where Group==Control to 5-7`
- Undo/redo:
  - `撤销`
  - `redo`
- Snapshots:
  - `保存快照 baseline`
  - `加载快照 baseline`
  - `查看快照`
- Plot:
  - `画图 type=line x=day y=il6 stats=on title=IL6 trend`
  - `plot type=scatter x=group y=value`

## API Summary

### `GET /health`
Returns `{"status":"ok"}`.

### `POST /api/session`
Creates a new session.

### `POST /api/upload?session_id=...`
Uploads CSV/Excel into session.

### `POST /api/chat`
Unified endpoint for chat/table/plot.

Request example:

```json
{
  "session_id": "optional-session-id",
  "message": "plot type=line x=day y=il6",
  "mode": "plot"
}
```

### `POST /api/plot/spec`
Validate/apply manual PlotSpec edits and regenerate preview payload.

### `POST /api/stats`
Compute stats for given PlotSpec and current session data.

### `GET /api/session/state`
Returns session metadata, table state, `undo_count`, `redo_count`, snapshot names.

### `GET /api/session/history`
Returns recent session action history (`action`, `summary`, `details`, timestamp).

### `POST /api/export/csv`
Export current table view (`active`) or source table (`original`) as CSV bytes.

### `POST /api/export/png`
Export PNG bytes (with fallback render path if primary render fails).

### `POST /api/export/pdf`
Export PDF bytes (with fallback render path if primary render fails).

## Environment Variables

- `OPENAI_API_KEY`
- `SUB2API_API_KEY`
- `SUB2API_BASE_URL`
- `MODEL_NAME`
- `REVIEW_MODEL_NAME`
- `MODEL_REASONING_EFFORT`
- `DISABLE_RESPONSE_STORAGE`
- `MODEL_NETWORK_ACCESS`
- `ENABLE_LEGACY_BACKEND_RENDER`
- `MPLCONFIGDIR`

## Tests

```bash
npm test
npm run test:py
npm run test:frontend
```

## Current Boundaries

- Sessions are primarily in-memory (lost after restart)
- No built-in multi-user auth/permissions yet
- Production deployment should add load testing, monitoring, and persistence

## Security Notes

- API keys are loaded from environment variables only
- Local file loading in chat is restricted to allowed roots
- PlotSpec is validated server-side before rendering
- Upload file type is whitelist-based (`csv/xlsx/xls`)
