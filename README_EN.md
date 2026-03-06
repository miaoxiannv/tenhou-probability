# SheetPilot Studio

A three-pane natural-language data visualization workspace.

- Left: Excel-like table preview/edit surface (via chat commands)
- Middle: chat agent with explicit modes (`auto`, `chat`, `plot`, `table`)
- Right: PlotSpec-first chart panel with editable spec and PDF export

## Overview

The backend is Spec-first: it returns structured `plot_spec` and `plot_payload`, then frontend renders charts directly from payload. The system supports CSV/Excel upload, table operations in chat, and layered/composed visualizations with optional stats overlay.

When model planning is unavailable, the backend falls back to a rule engine, so plotting and interactions still work.

## Core Features

- Session-based workflow (`POST /api/session`)
- Dataset upload: `.csv/.xlsx/.xls`
- Chat table controls:
  - load local file
  - preview/filter/sort/reset/clear
  - cell updates (`B1`, row/column, row ranges)
  - group-wise value clipping (e.g. clip `Expression` in `Control` to `5-7`)
  - undo/redo (`撤销` / `重做`, `undo` / `redo`)
  - snapshot checkpoints (`保存快照 baseline`, `加载快照 baseline`, `查看快照`)
- Chart types:
  - `scatter`, `line`, `bar`, `hist`, `box`, `violin`, `heatmap`, `composed`
- Advanced chart composition:
  - `layers` (`scatter/line/bar/hist/boxplot/violin/regression`)
  - `facet`
  - `stats_overlay`
- Stable plot policy for repeated prompts:
  - repeated same plot message in the same session reuses cached spec to avoid drift
- PDF export (`POST /api/export/pdf`)
- CSV export (`POST /api/export/csv`)
- Session observability:
  - current state (`GET /api/session/state`)
  - action history (`GET /api/session/history`)

## Productization Progress

Current maturity estimate: **~72%**.

- Already production-leaning:
  - mode-routed chat/table/plot flows
  - stable structured plot payloads
  - session history and export paths (PDF/CSV)
  - undo/redo + snapshots for table operations
- Still needed for “production-grade”:
  - persistent storage beyond in-memory sessions
  - multi-user auth/permissions
  - stronger E2E coverage and load testing

## Chat Modes

`/api/chat` supports a `mode` field:

- `auto` (default): intelligent routing between chat/table/plot
- `chat`: conversation only, no table mutation, no new plot generation
- `plot`: force plotting pipeline
- `table`: table command only

This makes behavior predictable in production and avoids accidental mode switching.

## Architecture (High Level)

1. User sends message to `/api/chat`
2. Backend routes by `mode`
3. For plot flow:
   - generate or update `plot_spec` (LLM or rule fallback)
   - validate spec against current table columns
   - build `plot_payload`
   - optionally compute statistical summary
4. Frontend renders payload and supports manual spec editing round-trip (`/api/plot/spec`)

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

Response includes:

- `summary`
- `table_state`
- `plot_spec`
- `plot_payload`
- `stats`
- `mode_used`
- `intent`

### `POST /api/plot/spec`
Validate/apply manual PlotSpec edits and regenerate preview payload.

### `POST /api/stats`
Compute stats for given PlotSpec and current session data.

### `GET /api/session/state`
Returns session metadata, table state, `undo_count`, `redo_count`, and snapshot names.

### `GET /api/session/history`
Returns recent session action history (`action`, `summary`, `details`, timestamp).

### `POST /api/export/pdf`
Export chart PDF bytes.

### `POST /api/export/csv`
Export current table view (`active`) or full source dataset (`original`) as CSV bytes.

## Environment Variables

- `OPENAI_API_KEY`
- `SUB2API_API_KEY`
- `SUB2API_BASE_URL`
- `MODEL_NAME`
- `ENABLE_LEGACY_BACKEND_RENDER`
- `MPLCONFIGDIR`

## Tests

```bash
npm test
npm run test:py
npm run test:frontend
```

## Security Notes

- API keys are loaded from environment variables only
- Local file loading in chat is restricted to allowed roots
- PlotSpec is validated server-side before rendering
- Upload file type is whitelist-based (`csv/xlsx/xls`)
