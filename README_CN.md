# 数据可视化工作台（NL Viz Studio）

一个三栏式自然语言数据可视化项目。

- 左侧：类 Excel 表格预览（可通过聊天指令控制）
- 中间：Chat Agent，支持显式模式 `auto/chat/plot/table`
- 右侧：PlotSpec-first 图表面板，可编辑参数并导出 PDF

## 项目概览

后端采用 Spec-first 架构：返回结构化 `plot_spec` 和 `plot_payload`，前端直接按 payload 渲染图表。

系统支持 CSV/Excel 上传、聊天控制表格、组合图层绘制、统计标注与 PDF 导出。

当模型不可用时，会自动回退到规则引擎，保证核心绘图流程不中断。

## 核心能力

- 会话机制（`POST /api/session`）
- 上传数据：`.csv/.xlsx/.xls`
- 聊天控表：
  - 加载本地文件
  - 预览 / 筛选 / 排序 / 重置 / 清空
  - 单元格修改（`B1`、行列索引、行区间）
  - 分组范围裁剪（例如把 `Control` 组 `Expression` 限制到 `5-7`）
- 图类型：
  - `scatter`、`line`、`bar`、`hist`、`box`、`violin`、`heatmap`、`composed`
- 高级组合：
  - `layers`（支持 `scatter/line/bar/hist/boxplot/violin/regression`）
  - `facet`
  - `stats_overlay`
- PDF 导出（`POST /api/export/pdf`）

## Chat 模式（Agent Skills 分层）

`/api/chat` 支持 `mode` 字段：

- `auto`（默认）：自动判断聊天/控表/画图
- `chat`：只对话，不修改表格，不新建图
- `plot`：强制走绘图链路
- `table`：只执行表格指令

这个分层可以避免误触发，提高可控性和专业性。

## 架构流程（简化）

1. 用户消息发送到 `/api/chat`
2. 后端根据 `mode` 进行路由
3. 若走绘图模式：
   - 生成或更新 `plot_spec`（模型或规则引擎）
   - 校验字段与列名合法性
   - 生成 `plot_payload`
   - 计算可用统计结果
4. 前端按 payload 渲染，并支持手改 spec 回传（`/api/plot/spec`）

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
统一入口（聊天 / 控表 / 画图）。

请求示例：

```json
{
  "session_id": "optional-session-id",
  "message": "plot type=line x=day y=il6",
  "mode": "plot"
}
```

响应关键字段：

- `summary`
- `table_state`
- `plot_spec`
- `plot_payload`
- `stats`
- `mode_used`
- `intent`

### `POST /api/plot/spec`
手动提交 PlotSpec 并重新预览。

### `POST /api/stats`
对当前会话数据 + PlotSpec 计算统计结果。

### `POST /api/export/pdf`
导出 PDF 文件流。

## 环境变量

- `OPENAI_API_KEY`
- `SUB2API_API_KEY`
- `SUB2API_BASE_URL`
- `MODEL_NAME`
- `ENABLE_LEGACY_BACKEND_RENDER`
- `MPLCONFIGDIR`

## 测试

```bash
npm test
npm run test:py
npm run test:frontend
```

## 安全说明

- API key 仅从环境变量读取
- 聊天加载本地文件限制在允许目录根
- PlotSpec 先后端校验再渲染
- 上传文件类型走白名单（`csv/xlsx/xls`）
