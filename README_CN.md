# 表格绘图智能体工作台（SheetPilot Studio）

一个三栏式自然语言数据可视化工作台。

- 左侧：类 Excel 数据表（上传、预览、编辑结果即时反馈）
- 中间：Chat Agent（支持 `auto/chat/plot/table` 模式）
- 右侧：PlotSpec-first 图表面板（参数编辑、统计标注、PNG/PDF 导出）

## 先看这里（阅读导航）

如果你是第一次接手这个项目，建议按下面顺序阅读：

1. 先看本 README 的「请求链路（最核心）」和「开发入口地图」。
2. 再看后端入口 `backend/main.py`（路由 + 会话 + 控表 + 绘图编排）。
3. 然后看 `frontend/src/App.jsx`（三栏状态流）和 `frontend/src/components/PlotCanvas.jsx`（Plotly 渲染）。

如果你只想快速上手使用：

1. 跳到「快速启动」。
2. 按「聊天指令示例」直接跑一轮上传 -> 控表 -> 绘图 -> 导出。

## 项目概览

后端采用 Spec-first 架构：统一返回结构化 `plot_spec` 和 `plot_payload`，前端不执行任意绘图脚本，只按 payload 渲染。

系统覆盖以下完整链路：

- CSV/Excel 上传
- 聊天控表（筛选、排序、改值、撤销重做、快照）
- 聊天绘图（模型优先，规则回退）
- 图层组合与统计标注
- 会话状态/历史可观测
- CSV/PNG/PDF 导出

当模型不可用或输出不合法时，会自动回退到规则引擎并尝试修复，保证流程尽量不中断。

## 核心能力

- 会话机制：`POST /api/session`
- 上传数据：`.csv/.xlsx/.xls`（30MB，最多 1,000,000 行）
- Chat 控表：
  - 加载本地文件
  - 预览 / 筛选 / 排序 / 重置 / 清空
  - 单元格修改（`B1`、行列索引、行区间）
  - 分组范围裁剪（例如把 `Control` 组 `Expression` 限制到 `5-7`）
  - 撤销 / 重做（`撤销`、`重做`）
  - 快照检查点（`保存快照 baseline`、`加载快照 baseline`、`查看快照`）
- 图类型：
  - `scatter`、`line`、`bar`、`hist`、`box`、`violin`、`heatmap`、`composed`
- 高级组合：
  - `layers`（`scatter/line/bar/hist/boxplot/violin/regression`）
  - `facet`
  - `stats_overlay`
- 稳定绘图策略：
  - 同一会话里重复同一绘图请求会复用缓存 spec，避免“同输入多图漂移”
- 导出：
  - CSV：`POST /api/export/csv`
  - PNG：`POST /api/export/png`
  - PDF：`POST /api/export/pdf`
- 会话可观测性：
  - 状态：`GET /api/session/state`
  - 历史：`GET /api/session/history`

## Chat 模式（`/api/chat`）

`mode` 字段用于强约束行为，避免误触发：

- `auto`（默认）：自动判断聊天/控表/绘图
- `chat`：只对话，不改表，不新建图
- `plot`：强制走绘图链路
- `table`：只执行表格指令

## 请求链路（最核心）

### A. 表格请求链路（table command）

1. 消息进入 `/api/chat`
2. 识别为表格指令（如 `筛选`、`set cell`、`撤销`）
3. 更新会话中的 `df/view_df/undo/redo/snapshots`
4. 返回最新 `table_state`，并尝试沿用当前 `last_plot_spec` 刷新图

### B. 绘图请求链路（plot intent）

1. 消息进入 `/api/chat`
2. 进入策略分流：
   - cache 命中：复用上次同请求 spec
   - 模板命中：规则模板直接生成
   - 显式编辑：基于当前 spec 增量修改
   - 否则模型规划：失败则规则回退
3. 校验 `plot_spec`（列名修正、参数约束、图层约束）
4. 构建 `plot_payload` + 可用统计结果
5. 返回 `execution_strategy` / `fallback_reason` / `mode_used` / `intent`

## 响应字段解读（`POST /api/chat`）

- `summary`：给用户的简短总结
- `plot_spec`：后端校验后的规范（可直接回传到 `/api/plot/spec`）
- `plot_payload`：前端绘图载荷（Plotly 渲染）
- `stats`：统计结果（条件不满足时可为 `null`）
- `execution_strategy`：本次决策路径（例如 `model_primary`、`rule_edit`、`cache_reuse`）
- `fallback_reason`：回退原因（例如 `missing_api_key`、`model_api_or_parse_error`）
- `mode_used`：实际模式
- `intent`：后端识别的意图（`chat/table/plot`）
- `thinking`：裁剪后的执行轨迹

## 开发入口地图

```text
backend/main.py
  ├─ 路由层：/api/chat /api/upload /api/export/*
  ├─ 会话层：SessionData、undo/redo/snapshots/history/cache
  ├─ 指令层：表格命令解析与执行（load/filter/sort/update/undo/redo/snapshot）
  └─ 编排层：模型规划 -> 规则回退 -> spec 校验 -> payload 构建

backend/spec_utils.py
  └─ PlotSpec schema/字段修正/合法性校验/过滤执行

backend/plot_payload.py
  └─ 将 DataFrame + PlotSpec 转成前端可渲染 payload（layers/facets/stats）

backend/stats_engine.py
  └─ Welch t-test / ANOVA / permutation fallback

frontend/src/App.jsx
  └─ 三栏状态管理（会话、聊天、spec、payload、导出）

frontend/src/components/PlotCanvas.jsx
  └─ Plotly traces/layout 构建（含 regression、facet、双轴）
```

## 目录结构

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

## 快速启动

```bash
cd /home/zhang/tenhou-probability

python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

npm run frontend:install
npm run frontend:build

cp .env.example .env
./scripts/run_server.sh
```

打开：`http://127.0.0.1:8888`

## 开发模式

```bash
# 后端
npm run dev:py

# 前端
npm run frontend:dev
```

前端开发地址：`http://127.0.0.1:5173`

## 聊天指令示例

- 加载文件：
  - `加载文件 /home/zhang/data.csv`
  - `load file /home/zhang/data.csv`
- 修改单元格：
  - `把第一行第二列的值改成2`
  - `set cell B1 to 8`
- 区间批量修改：
  - `把第1到10行第2列的值改成0`
  - `set rows 1-10 col 2 to 0`
- 分组裁剪：
  - `把Group中的Control组的所有Expression的范围更改为5-7`
  - `clip Expression where Group==Control to 5-7`
- 撤销/重做：
  - `撤销`
  - `redo`
- 快照：
  - `保存快照 baseline`
  - `加载快照 baseline`
  - `查看快照`
- 绘图：
  - `画图 type=line x=day y=il6 stats=on title=IL6 trend`
  - `plot type=scatter x=group y=value`

## API 说明

### `GET /health`
返回 `{"status":"ok"}`。

### `POST /api/session`
创建会话。

### `POST /api/upload?session_id=...`
上传 CSV/Excel 到会话。

### `POST /api/chat`
统一入口（聊天 / 控表 / 绘图）。

请求示例：

```json
{
  "session_id": "optional-session-id",
  "message": "plot type=line x=day y=il6",
  "mode": "plot"
}
```

### `POST /api/plot/spec`
手动提交 PlotSpec 并重新预览。

### `POST /api/stats`
对当前会话数据 + PlotSpec 计算统计结果。

### `GET /api/session/state`
返回会话元信息、表格状态、`undo_count`、`redo_count` 和快照列表。

### `GET /api/session/history`
返回会话操作历史（`action`、`summary`、`details`、时间戳）。

### `POST /api/export/csv`
将当前视图（`active`）或原始数据（`original`）导出为 CSV 文件流。

### `POST /api/export/png`
导出 PNG 文件流（后端渲染失败时会尝试降级 spec）。

### `POST /api/export/pdf`
导出 PDF 文件流（后端渲染失败时会尝试降级 spec）。

## 环境变量

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

## 测试

```bash
npm test
npm run test:py
npm run test:frontend
```

## 当前边界

- 会话目前以内存为主，服务重启后会丢失
- 尚未内建多用户鉴权和权限模型
- 生产部署前建议补充压测、监控与持久化方案

## 安全说明

- API key 仅从环境变量读取
- 聊天加载本地文件限制在允许目录根
- PlotSpec 先后端校验再渲染
- 上传文件类型走白名单（`csv/xlsx/xls`）
