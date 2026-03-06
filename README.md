# NL Viz Studio / 数据可视化工作台

> CN: 一个三栏式的自然语言数据可视化工具。支持上传 CSV/Excel，聊天控制数据视图，生成结构化 PlotSpec，并在前端实时渲染、编辑和导出 PDF。  
> EN: A three-pane natural-language data visualization workspace. Upload CSV/Excel, control table views via chat, generate structured PlotSpec, render/edit charts in frontend, and export PDF.

## 1) Overview / 项目概览

| 中文 | English |
|---|---|
| 左侧是表格预览面板，文件上传后自动解析并展示前 50 行。 | Left pane is a table preview panel; uploaded files are parsed automatically and first 50 rows are shown. |
| 中间是 Chat Agent，可直接发送自然语言执行“筛选、排序、重置、清空、绘图”。 | Center pane is a Chat Agent for natural-language filtering, sorting, reset, clear, and plotting. |
| 右侧是图表面板，支持 PlotSpec 参数编辑、多图层组合、分面、统计标注和 PDF 导出。 | Right pane is a chart panel with PlotSpec editing, layered composition, faceting, stats overlay, and PDF export. |
| 后端是 Spec-first：返回结构化规范和渲染载荷，不返回可执行绘图代码给前端。 | Backend is Spec-first: returns structured spec and payload, not executable plotting scripts for frontend. |
| 模型不可用时会自动降级到规则引擎，保证会话和绘图流程不断。 | If model is unavailable, it automatically falls back to a rule engine to keep workflow running. |

## 2) Core Features / 核心能力

| 中文 | English |
|---|---|
| 会话机制：`POST /api/session` 返回 `session_id`，数据和图配置在会话中维护（内存态）。 | Session-based workflow: `POST /api/session` returns `session_id`; data/spec live in memory per session. |
| 上传数据：支持 `.csv/.xlsx/.xls`，单文件最大 30MB，最大 1,000,000 行。 | Dataset upload: supports `.csv/.xlsx/.xls`, max 30MB per file, max 1,000,000 rows. |
| 聊天控表：支持 `预览`、`筛选`、`排序`、`重置`、`清空数据`、`加载文件 /path/file.csv`。 | Table commands in chat: preview, filter, sort, reset, clear data, load local file by path. |
| 图类型：`scatter/line/bar/hist/box/violin/heatmap/composed`。 | Chart types: `scatter/line/bar/hist/box/violin/heatmap/composed`. |
| 高级组合：`layers`（mark 可为 `scatter/line/bar/hist/boxplot/violin/regression`）+ `facet` + `stats_overlay`。 | Advanced composition: `layers` (mark supports `scatter/line/bar/hist/boxplot/violin/regression`) + `facet` + `stats_overlay`. |
| 统计检验：两组用 Welch t-test，多组用 One-way ANOVA；若无 scipy 使用置换检验。 | Statistics: Welch t-test for 2 groups, One-way ANOVA for multi-group; permutation fallback if scipy is missing. |
| 前端渲染：基于 Plotly 渲染 payload，支持右轴 `y2`、回归线 CI、分面网格。 | Frontend rendering: Plotly payload rendering, supports right y-axis `y2`, regression CI, facet grid. |
| PDF 导出：`POST /api/export/pdf` 返回 `application/pdf` 文件流。 | PDF export: `POST /api/export/pdf` returns `application/pdf` stream. |

## 3) Architecture / 架构说明

### Spec-first flow / 主流程

1. 用户在聊天中提出需求（绘图/编辑/统计/控表）。  
   User sends natural-language request in chat.
2. 后端优先生成结构化 `plot_spec`（模型规划或规则引擎 fallback）。  
   Backend generates structured `plot_spec` (LLM planner or rule-engine fallback).
3. 后端校验 `plot_spec`（字段、图层、列名匹配、参数范围、过滤条件合法性）。  
   Backend validates the `plot_spec` (schema, layer fields, column matching, ranges, filters).
4. 后端根据当前表格视图生成 `plot_payload` 并计算统计信息。  
   Backend builds `plot_payload` from current table view and computes stats.
5. 前端基于 `plot_payload` 渲染图表，并允许再次编辑参数回传。  
   Frontend renders chart from `plot_payload` and can round-trip edited parameters.

### Compatibility flow / 兼容流程

- 若 `ENABLE_LEGACY_BACKEND_RENDER=true`，`/api/chat` 会附带 `legacy_image_base64`。  
  If `ENABLE_LEGACY_BACKEND_RENDER=true`, `/api/chat` also returns `legacy_image_base64`.

## 4) Project Structure / 目录结构

```text
.
├── backend/
│   ├── main.py               # FastAPI app + sessions + chat orchestration + API routes
│   ├── spec_utils.py         # PlotSpec schema parsing/validation/filter application
│   ├── plot_payload.py       # Build frontend payload (layers/facets/stats overlay)
│   ├── stats_engine.py       # Welch t-test / ANOVA / permutation fallback
│   ├── plot_engine.py        # Legacy backend rendering + PDF bytes generation
│   ├── llm_client.py         # Responses API wrapper (sub2api/OpenAI compatible)
│   └── tests/                # Python unit tests
├── frontend/
│   ├── src/App.jsx           # 3-pane app state management
│   ├── src/components/       # DataPane / ChatPane / PlotPane / PlotCanvas
│   ├── src/api/client.js     # API client wrappers
│   ├── vite.config.js        # Vite dev server + proxy config
│   └── package.json
├── scripts/
│   ├── run_server.sh         # Load env + run uvicorn on 8888
│   └── stop_server.sh        # Stop uvicorn process
├── requirements.txt
├── package.json
└── README.md
```

## 5) Prerequisites / 环境要求

| 中文 | English |
|---|---|
| 建议 Python 3.10+（项目内示例使用 `.venv`）。 | Python 3.10+ is recommended (project uses local `.venv`). |
| Node.js 18+（用于 React/Vite）。 | Node.js 18+ (for React/Vite). |
| 可选：`scipy`（提升统计检验速度和精度）。 | Optional: `scipy` for faster/more robust statistical tests. |

## 6) Quick Start (Production-like) / 快速启动（接近生产）

### Step 1: install dependencies / 安装依赖

```bash
cd /home/zhang/tenhou-probability

# Python deps
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# Frontend deps
npm run frontend:install
```

### Step 2: configure environment / 配置环境变量

```bash
cp .env.example .env
```

`OPENAI_API_KEY` 或 `SUB2API_API_KEY` 可选；不配置时可走规则引擎（基础绘图能力可用）。  
`OPENAI_API_KEY` or `SUB2API_API_KEY` is optional; without it, rule-engine fallback still works for base plotting.

### Step 3: build frontend / 构建前端

```bash
npm run frontend:build
```

### Step 4: start backend server / 启动后端服务

```bash
./scripts/run_server.sh
```

### Step 5: open app / 打开页面

```text
http://127.0.0.1:8888
```

## 7) Development Mode / 开发模式

### Backend with reload / 后端热更新

```bash
npm run dev:py
```

### Frontend dev server / 前端开发服务

```bash
npm run frontend:dev
```

说明 / Notes:

- 前端默认在 `http://127.0.0.1:5173`。  
  Frontend dev server default: `http://127.0.0.1:5173`.
- Vite 会将 `/api` 和 `/health` 代理到 `http://127.0.0.1:8888`。  
  Vite proxies `/api` and `/health` to `http://127.0.0.1:8888`.

## 8) Chat Usage / 聊天指令示例

| 中文示例 | English Example |
|---|---|
| `加载文件 /home/zhang/data.csv` | `load file /home/zhang/data.csv` |
| `预览` / `显示前 20 行` | `show` / `show top 20 rows` |
| `筛选 group == A` | `filter group == A` |
| `按 value 降序` | `sort by value desc` |
| `重置` | `reset` |
| `清空数据` | `clear data` |
| `画一个散点图，x=day，y=il6，按group分组` | `make a scatter plot, x=day, y=il6, group by group` |
| `把颜色改成 Blues，标题改为 IL6 trend` | `set palette to Blues and title to IL6 trend` |

数据路径安全限制 / Local file safety boundaries:

- 聊天加载本地文件仅允许以下根目录：项目目录、`/home/zhang`、`/tmp`。  
  Chat file loading only allows roots: project root, `/home/zhang`, `/tmp`.

## 9) API Reference / 接口说明

### `GET /health`

- CN: 健康检查，返回 `{"status":"ok"}`。  
  EN: Health check endpoint, returns `{"status":"ok"}`.

### `POST /api/session`

- CN: 创建会话，返回 `session_id`。  
  EN: Create a new session and return `session_id`.

### `POST /api/upload?session_id=...`

- CN: 上传并解析文件，更新会话中的表格。  
  EN: Upload and parse dataset into session state.
- 支持格式 / Allowed types: `.csv`, `.xlsx`, `.xls`
- 限制 / Limits: max 30MB, max 1,000,000 rows

### `POST /api/chat`

- CN: 统一入口。既可普通问答，也可控表、生成/编辑图规范并返回渲染 payload。  
  EN: Unified chat endpoint for QA, table commands, and plot generation/editing.

Request example:

```json
{
  "session_id": "optional_session_id",
  "message": "按 group 分组做箱线+散点叠加图，并打开统计标注"
}
```

Response core fields:

```json
{
  "session_id": "....",
  "summary": "已按请求生成 composed 图。",
  "used_fallback": false,
  "plot_spec": {},
  "plot_payload": {},
  "stats": {},
  "warnings": [],
  "thinking": [],
  "table_state": {},
  "legacy_image_base64": "",
  "raw_model_text": ""
}
```

### `POST /api/plot/spec`

- CN: 手动编辑 PlotSpec 后，后端重新校验并返回预览数据。  
  EN: Validate edited PlotSpec and regenerate preview payload.

### `POST /api/stats`

- CN: 基于当前会话数据和给定 PlotSpec 单独计算统计结果。  
  EN: Compute stats from current session data and provided PlotSpec.

### `POST /api/export/pdf`

- CN: 导出 PDF 文件流。  
  EN: Export chart as PDF stream.

Request example:

```json
{
  "session_id": "....",
  "plot_spec": {},
  "filename": "my_chart.pdf"
}
```

## 10) PlotSpec Model / PlotSpec 结构

典型字段 / Common fields:

- `chart_type`: `scatter|line|bar|hist|box|violin|heatmap|composed`
- `x`, `y`, `hue`
- `palette`, `title`, `agg`, `bins`
- `filters`: list of `{column, op, value}`, `op` 支持 `== != > >= < <= in`
- `layers`: advanced composed layers
- `facet`: `{field, columns}`
- `stats_overlay`: `{enabled, method}`
- `style`: extra rendering metadata (例如 `theme`, `units`)

Example:

```json
{
  "chart_type": "composed",
  "data_ref": "active_dataset",
  "encoding": { "x": "group", "y": "IL6", "color": "condition" },
  "layers": [
    {
      "mark": "boxplot",
      "encoding": { "x": "group", "y": "IL6" },
      "box_width": 0.4
    },
    {
      "mark": "scatter",
      "encoding": { "x": "group", "y": "IL6", "hue": "condition" },
      "jitter": true,
      "alpha": 0.52
    },
    {
      "mark": "regression",
      "encoding": { "x": "day", "y": "IL6", "hue": "condition" },
      "ci": true
    }
  ],
  "facet": { "field": "batch", "columns": 3 },
  "stats_overlay": { "enabled": true, "method": "auto" },
  "style": { "theme": "light", "title": "IL6 layers" },
  "filters": [
    { "column": "group", "op": "!=", "value": "unknown" }
  ]
}
```

## 11) Statistical Behavior / 统计行为

| 中文 | English |
|---|---|
| 如果 `y` 不是数值列，则跳过统计。 | Stats are skipped if `y` is not numeric. |
| 自动选择分组列：优先 `hue`，其次 `x`。 | Group column selection: `hue` first, then `x`. |
| 两组比较：Welch t-test（有 scipy）或置换 Welch（无 scipy）。 | Two-group test: Welch t-test (scipy) or permutation Welch fallback. |
| 多组比较：One-way ANOVA（有 scipy）或置换 ANOVA（无 scipy）。 | Multi-group test: One-way ANOVA (scipy) or permutation ANOVA fallback. |
| 输出含 `p_value`、`significance_stars`、`effect_size`、`effect_metric`。 | Outputs include `p_value`, `significance_stars`, `effect_size`, and `effect_metric`. |

## 12) Environment Variables / 环境变量

| 变量 | 默认值 | 说明（中文 / English） |
|---|---|---|
| `OPENAI_API_KEY` | empty | 模型 API key，可与 `SUB2API_API_KEY` 二选一。 / Model API key; can be used instead of `SUB2API_API_KEY`. |
| `SUB2API_API_KEY` | empty | 与 `OPENAI_API_KEY` 等价备用。 / Alternative key name accepted by the app. |
| `SUB2API_BASE_URL` | `http://sub2api.chenlabs.online` | Responses API base URL. |
| `MODEL_NAME` | `gpt-5.3-codex` | 主模型名称 / main model ID. |
| `REVIEW_MODEL_NAME` | `gpt-5.3-codex` | 评审模型名称（预留）/ review model ID (reserved). |
| `MODEL_REASONING_EFFORT` | `xhigh` | reasoning effort. |
| `DISABLE_RESPONSE_STORAGE` | `true` | 是否禁用响应持久化。 / Disable response storage when true. |
| `MODEL_NETWORK_ACCESS` | `enabled` | 模型网络策略标识（透传配置）。 / Model network access tag (pass-through). |
| `ENABLE_LEGACY_BACKEND_RENDER` | `false` | 开启后返回 `legacy_image_base64`。 / Return `legacy_image_base64` when enabled. |
| `MPLCONFIGDIR` | `/tmp/mplconfig` | matplotlib 缓存目录。 / matplotlib cache directory. |

## 13) Testing / 测试

```bash
# root JS tests
npm test

# Python tests
npm run test:py

# frontend tests
npm run test:frontend
```

## 14) Operational Limits / 运行限制

| 中文 | English |
|---|---|
| 会话状态保存在内存中，重启服务后会丢失。 | Session state is in-memory and will be lost after restart. |
| 大数据时图层会抽样（默认上限约 6000 点）以保证前端渲染稳定。 | For large datasets, layers are sampled (default around 6000 points) for stable rendering. |
| 分面最多渲染 12 个类别。 | Faceting renders up to 12 categories. |
| `facet.columns` 要在 1 到 6 之间。 | `facet.columns` must be between 1 and 6. |
| 双轴图若未提供 `style.units.right` 会自动降级为单轴。 | Dual-axis falls back to single-axis if `style.units.right` is missing. |

## 15) Security Notes / 安全说明

- API key 仅通过环境变量读取，不写入源码。  
  API keys are read from environment variables only.
- 上传文件类型白名单：`.csv/.xlsx/.xls`。  
  Upload type whitelist: `.csv/.xlsx/.xls`.
- PlotSpec 会经过后端严格校验，不合法直接返回 400。  
  PlotSpec is validated server-side and invalid specs return HTTP 400.
- 本地路径加载限制在允许目录根，避免任意路径读取。  
  Local path loading is restricted to allowed root directories.

## 16) Troubleshooting / 常见问题

### 1. 前端提示无法连接后端 / Frontend says backend is unreachable

```bash
cd /home/zhang/tenhou-probability
./scripts/run_server.sh
curl -sS http://127.0.0.1:8888/health
```

### 2. 未配置 API key / API key is missing

- 现象 / Symptom: 聊天仍可用，但会使用规则引擎，复杂规划能力下降。  
  Chat still works via rule engine, but complex planning quality may be lower.

### 3. PDF 导出失败 / PDF export fails

- 检查 `plot_spec` 是否可渲染。  
  Check whether `plot_spec` is renderable.
- 检查后端日志中的具体异常。  
  Check backend logs for detailed exception.

---

If you plan to deploy or publish this repository, keep `.env` out of version control and rotate keys regularly.  
如果计划部署或公开此仓库，请确保 `.env` 不入库，并定期轮换密钥。
