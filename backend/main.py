from __future__ import annotations

import base64
import io
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .config import load_config
from .llm_client import call_responses_api
from .plot_payload import build_plot_payload
from .plot_engine import render_plot
from .spec_utils import PlotSpec, parse_json_from_model_output, resolve_column_name, validate_plot_spec
from .stats_engine import compute_pvalue

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"
MAX_UPLOAD_MB = 30
MAX_ROWS = 1_000_000
PREVIEW_ROWS = 50
MAX_TRACE_STEPS = 20
TABLE_OPS = {"==", "!=", ">", ">=", "<", "<="}
LEGACY_STATIC_FILES = {
    "index.html",
    "styles.css",
    "app.js",
    "simulator.js",
    "tower-engine.js",
    "worker.js",
}
DATA_ALLOWED_ROOTS = [ROOT_DIR.resolve(), Path("/home/zhang").resolve(), Path("/tmp").resolve()]

PALETTE_KEYWORDS = {
    "红": "Reds",
    "蓝": "Blues",
    "绿": "Greens",
    "橙": "Oranges",
    "紫": "Purples",
    "灰": "Greys",
    "黄": "YlOrBr",
    "pink": "flare",
    "viridis": "viridis",
    "magma": "magma",
    "inferno": "inferno",
    "cividis": "cividis",
}
PLOT_INTENT_KEYWORDS = (
    "plot",
    "chart",
    "scatter",
    "line",
    "bar",
    "hist",
    "box",
    "violin",
    "heatmap",
    "画图",
    "绘图",
    "图表",
    "散点",
    "折线",
    "柱状",
    "柱形",
    "直方",
    "箱线",
    "小提琴",
    "热图",
    "相关",
    "x轴",
    "y轴",
    "横轴",
    "纵轴",
    "hue",
    "palette",
    "调色板",
    "颜色",
    "标题",
    "title",
    "agg",
    "聚合",
    "bins",
    "分箱",
    "组合图",
    "叠加",
    "分面",
    "facet",
    "回归",
    "置信区间",
    "双轴",
    "双y轴",
    "raincloud",
)
EDIT_VERB_PATTERN = re.compile(
    r"(改成|改为|改一下|调整|设为|设置为|变成|切换|取消|去掉|不要|change|set|update|remove)",
    flags=re.IGNORECASE,
)


@dataclass
class SessionData:
    df: pd.DataFrame
    filename: str
    view_df: pd.DataFrame | None = None
    last_plot_spec: PlotSpec | None = None


SESSIONS: dict[str, SessionData] = {}


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=8, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class SpecRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)
    plot_spec: dict[str, Any]


class ExportPdfRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)
    plot_spec: dict[str, Any]
    filename: str | None = Field(default=None, max_length=120)


app = FastAPI(title="NL Viz Studio", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/session")
def create_session() -> dict[str, str]:
    session_id = uuid.uuid4().hex
    return {"session_id": session_id}


def _active_df(session: SessionData) -> pd.DataFrame:
    if session.view_df is not None:
        return session.view_df
    return session.df


def _to_preview_rows(df: pd.DataFrame, rows: int = PREVIEW_ROWS) -> list[dict[str, Any]]:
    preview_df = df.head(rows).copy()
    preview_df = preview_df.where(pd.notnull(preview_df), None)
    return preview_df.to_dict(orient="records")


def _columns_meta(df: pd.DataFrame) -> list[dict[str, Any]]:
    meta: list[dict[str, Any]] = []
    for col in df.columns:
        series = df[col]
        meta.append(
            {
                "name": col,
                "dtype": str(series.dtype),
                "missing": int(series.isna().sum()),
                "unique": int(series.nunique(dropna=True)),
            }
        )
    return meta


def _table_state(session: SessionData, *, preview_rows: int = PREVIEW_ROWS) -> dict[str, Any]:
    active = _active_df(session)
    return {
        "filename": session.filename,
        "row_count": int(len(active)),
        "source_row_count": int(len(session.df)),
        "column_count": int(len(active.columns)),
        "columns": _columns_meta(active),
        "preview_rows": _to_preview_rows(active, rows=preview_rows),
    }


def _read_dataframe_from_upload(file: UploadFile, file_bytes: bytes) -> pd.DataFrame:
    name = (file.filename or "").lower()

    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))

    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(file_bytes))

    raise HTTPException(status_code=400, detail="Only CSV/XLSX files are supported")


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Remove fully empty columns.
    df = df.dropna(axis=1, how="all")

    if df.empty:
        raise HTTPException(status_code=400, detail="No usable rows/columns in file")

    if len(df) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"Too many rows (> {MAX_ROWS})")

    return df


def _read_dataframe_from_path(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("Only CSV/XLSX files are supported")


def _is_under_allowed_root(path: Path) -> bool:
    for root in DATA_ALLOWED_ROOTS:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _resolve_local_data_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip("'").strip('"')
    if not cleaned:
        raise ValueError("文件路径为空")

    candidate = Path(cleaned).expanduser()
    if candidate.is_absolute():
        candidate = candidate.resolve()
    else:
        candidate = (ROOT_DIR / candidate).resolve()

    if not _is_under_allowed_root(candidate):
        raise ValueError("文件路径超出允许范围（仅支持项目目录、/home/zhang、/tmp）")
    if not candidate.exists() or not candidate.is_file():
        raise ValueError(f"文件不存在：{candidate}")
    if candidate.suffix.lower() not in {".csv", ".xlsx", ".xls"}:
        raise ValueError("仅支持 .csv/.xlsx/.xls 文件")

    return candidate


def _parse_scalar_value(raw: str) -> Any:
    text = raw.strip().strip("，。")
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]

    lowered = text.lower()
    if lowered in {"null", "none"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    try:
        if "." in text or "e" in lowered:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _table_command_from_message(message: str) -> dict[str, Any] | None:
    text = message.strip()
    if not text:
        return None

    for pattern in [
        r"^(?:加载|导入|打开|读取)\s*(?:文件|数据集|dataset)?\s*[:：]?\s*(.+)$",
        r"^(?:load|open|read)\s+(?:file|dataset)?\s*[:=]?\s*(.+)$",
    ]:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"action": "load_file", "path": match.group(1).strip()}

    if re.match(r"^.+\.(?:csv|xlsx|xls)$", text, flags=re.IGNORECASE):
        return {"action": "load_file", "path": text}

    preview_match = re.match(
        r"^(?:预览|查看|显示|show)(?:\s*(?:前|top)?\s*(\d{1,3})\s*(?:行|rows?)?)?$",
        text,
        flags=re.IGNORECASE,
    )
    if preview_match:
        rows = int(preview_match.group(1)) if preview_match.group(1) else PREVIEW_ROWS
        return {"action": "preview", "rows": rows}

    sort_match_cn = re.match(
        r"^(?:按|根据)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*(升序|降序)$",
        text,
        flags=re.IGNORECASE,
    )
    if sort_match_cn:
        return {
            "action": "sort",
            "column": sort_match_cn.group(1).strip(),
            "ascending": sort_match_cn.group(2) == "升序",
        }

    sort_match_en = re.match(
        r"^sort\s+by\s+([^\s]+)(?:\s+(asc|desc))?$",
        text,
        flags=re.IGNORECASE,
    )
    if sort_match_en:
        return {
            "action": "sort",
            "column": sort_match_en.group(1).strip(),
            "ascending": (sort_match_en.group(2) or "asc").lower() != "desc",
        }

    filter_match = re.match(
        r"^(?:筛选|过滤|filter)\s+([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*(==|=|!=|>=|<=|>|<)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if filter_match:
        return {
            "action": "filter",
            "column": filter_match.group(1).strip(),
            "op": filter_match.group(2),
            "value": _parse_scalar_value(filter_match.group(3)),
        }

    if re.match(r"^(?:重置(?:数据|表格|视图)?|恢复原表|reset(?:\s+table|\s+data|\s+view)?)$", text, flags=re.IGNORECASE):
        return {"action": "reset_view"}

    if re.match(r"^(?:清空(?:数据|表格)?|remove\s+data|clear\s+data)$", text, flags=re.IGNORECASE):
        return {"action": "clear_data"}

    return None


def _apply_single_filter(df: pd.DataFrame, column: str, op: str, value: Any) -> pd.DataFrame:
    if op == "=":
        op = "=="
    if op not in TABLE_OPS:
        raise ValueError(f"不支持的操作符：{op}")

    series = df[column]
    target = value
    if pd.api.types.is_numeric_dtype(series) and target is not None and not isinstance(target, bool):
        target = pd.to_numeric(pd.Series([target]), errors="raise").iloc[0]

    if op == "==":
        return df[df[column] == target]
    if op == "!=":
        return df[df[column] != target]
    if op == ">":
        return df[df[column] > target]
    if op == ">=":
        return df[df[column] >= target]
    if op == "<":
        return df[df[column] < target]
    return df[df[column] <= target]


def _execute_table_command(
    *,
    command: dict[str, Any],
    session_id: str,
    session: SessionData | None,
    trace: list[str],
) -> tuple[str, SessionData | None, int]:
    action = command.get("action")
    preview_rows = PREVIEW_ROWS

    if action == "load_file":
        path = _resolve_local_data_path(str(command.get("path", "")))
        df = _sanitize_dataframe(_read_dataframe_from_path(path))
        loaded = SessionData(df=df, filename=path.name, view_df=df.copy(), last_plot_spec=None)
        SESSIONS[session_id] = loaded
        trace.append(f"已通过 chat 加载文件：{path}")
        return (
            f"已加载文件 {path.name}，共 {len(df)} 行 {len(df.columns)} 列。现在可直接要求绘图或继续筛选数据。",
            loaded,
            preview_rows,
        )

    if not session:
        return (
            "当前还没有可操作的数据。你可以直接在聊天里输入：`加载文件 /home/zhang/xxx.csv`。",
            None,
            preview_rows,
        )

    if action == "preview":
        preview_rows = max(1, min(int(command.get("rows", PREVIEW_ROWS)), 200))
        active = _active_df(session)
        trace.append(f"刷新预览：前 {preview_rows} 行")
        return (
            f"已刷新预览，当前显示前 {preview_rows} 行（数据总行数 {len(active)}）。",
            session,
            preview_rows,
        )

    if action == "reset_view":
        session.view_df = session.df.copy()
        trace.append("已重置为原始数据视图")
        return ("已重置筛选/排序，恢复到原始数据视图。", session, preview_rows)

    if action == "clear_data":
        SESSIONS.pop(session_id, None)
        trace.append("已清空会话中的数据")
        return ("已清空当前会话数据。可继续聊天，或发送“加载文件 路径”重新载入。", None, preview_rows)

    active = _active_df(session)
    columns = [str(c) for c in active.columns]

    if action == "sort":
        requested = str(command.get("column", "")).strip()
        ascending = bool(command.get("ascending", True))
        try:
            resolved = resolve_column_name(requested, columns, field_name="sort", notes=trace)
        except ValueError:
            return (f"未找到排序列：{requested}。请使用现有列名。", session, preview_rows)
        if not resolved:
            return ("排序指令缺少列名。", session, preview_rows)

        session.view_df = active.sort_values(by=resolved, ascending=ascending, kind="stable").reset_index(drop=True)
        order_text = "升序" if ascending else "降序"
        trace.append(f"已按 {resolved} {order_text} 排序")
        return (f"已按列 {resolved} {order_text} 排序。", session, preview_rows)

    if action == "filter":
        requested = str(command.get("column", "")).strip()
        op = str(command.get("op", "==")).strip()
        value = command.get("value")
        try:
            resolved = resolve_column_name(requested, columns, field_name="filter", notes=trace)
        except ValueError:
            return (f"未找到筛选列：{requested}。请使用现有列名。", session, preview_rows)
        if not resolved:
            return ("筛选指令缺少列名。", session, preview_rows)

        try:
            filtered = _apply_single_filter(active, resolved, op, value)
        except Exception as exc:
            return (f"筛选失败：{exc}", session, preview_rows)

        session.view_df = filtered.reset_index(drop=True)
        trace.append(f"筛选完成：{resolved} {op} {value}，剩余 {len(session.view_df)} 行")
        return (f"筛选完成：{resolved} {op} {value}，当前剩余 {len(session.view_df)} 行。", session, preview_rows)

    return ("已识别到表格指令，但暂未实现该动作。", session, preview_rows)


@app.post("/api/upload")
async def upload_file(session_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if not session_id or len(session_id) < 8:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (> {MAX_UPLOAD_MB}MB)")

    try:
        df = _read_dataframe_from_upload(file, file_bytes)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Failed to read file: {exc}") from exc

    df = _sanitize_dataframe(df)

    session = SessionData(df=df, filename=file.filename or "uploaded_file", view_df=df.copy(), last_plot_spec=None)
    SESSIONS[session_id] = session
    state = _table_state(session)

    return {
        "session_id": session_id,
        "filename": state["filename"],
        "row_count": state["row_count"],
        "source_row_count": state["source_row_count"],
        "column_count": state["column_count"],
        "columns": state["columns"],
        "preview_rows": state["preview_rows"],
    }


def _infer_unit_from_column(col_name: str | None) -> str | None:
    if not col_name:
        return None
    text = str(col_name)
    match = re.search(r"\(([^)]+)\)|\[([^\]]+)\]", text)
    if not match:
        return None
    unit = (match.group(1) or match.group(2) or "").strip()
    return unit or None


def _guess_advanced_spec(message: str, columns: list[str]) -> dict[str, Any] | None:
    lower = message.lower()
    if len(columns) < 2:
        return None

    x = columns[0]
    y = columns[1]
    group = columns[2] if len(columns) > 2 else None

    scatter_box_tokens = [
        "散点+箱线",
        "散点加箱线",
        "scatter+box",
        "scatter box",
        "scatter and box",
    ]
    if any(token in message or token in lower for token in scatter_box_tokens):
        x_field = group or x
        return {
            "chart_type": "composed",
            "encoding": {"x": x_field, "y": y, "color": group},
            "layers": [
                {"mark": "boxplot", "encoding": {"x": x_field, "y": y}, "box_width": 0.45, "alpha": 0.5},
                {"mark": "scatter", "encoding": {"x": x_field, "y": y, "hue": group}, "jitter": True, "alpha": 0.58},
            ],
            "stats_overlay": {"enabled": True, "method": "auto"},
            "style": {"title": "Scatter + Box"},
        }

    rain_tokens = [
        "raincloud",
        "小提琴+箱线",
        "小提琴加箱线",
        "violin+box",
    ]
    if any(token in message or token in lower for token in rain_tokens):
        x_field = group or x
        return {
            "chart_type": "composed",
            "encoding": {"x": x_field, "y": y, "color": group},
            "layers": [
                {"mark": "violin", "encoding": {"x": x_field, "y": y, "hue": group}, "alpha": 0.35},
                {"mark": "boxplot", "encoding": {"x": x_field, "y": y, "hue": group}, "box_width": 0.3, "alpha": 0.65},
                {"mark": "scatter", "encoding": {"x": x_field, "y": y, "hue": group}, "jitter": True, "alpha": 0.42},
            ],
            "stats_overlay": {"enabled": True, "method": "auto"},
            "style": {"title": "Violin + Box + Jitter"},
        }

    reg_tokens = [
        "回归",
        "regression",
        "置信区间",
        "confidence interval",
    ]
    if any(token in message or token in lower for token in reg_tokens):
        return {
            "chart_type": "composed",
            "encoding": {"x": x, "y": y, "color": group},
            "layers": [
                {"mark": "scatter", "encoding": {"x": x, "y": y, "hue": group}, "alpha": 0.55},
                {"mark": "regression", "encoding": {"x": x, "y": y, "hue": group}, "ci": True},
            ],
            "stats_overlay": {"enabled": False, "method": "auto"},
            "style": {"title": "Grouped Scatter + Regression"},
        }

    facet_tokens = [
        "分面",
        "facet",
        "多子图",
        "small multiple",
    ]
    if any(token in message or token in lower for token in facet_tokens):
        facet_field = group or x
        return {
            "chart_type": "composed",
            "encoding": {"x": x, "y": y, "color": group},
            "layers": [
                {"mark": "scatter", "encoding": {"x": x, "y": y, "hue": group}, "alpha": 0.62},
            ],
            "facet": {"field": facet_field, "columns": 3},
            "stats_overlay": {"enabled": False, "method": "auto"},
            "style": {"title": f"Facet by {facet_field}"},
        }

    dual_tokens = [
        "双轴",
        "双y轴",
        "dual axis",
        "secondary axis",
    ]
    if any(token in message or token in lower for token in dual_tokens) and len(columns) > 2:
        y_right = columns[2]
        unit_left = _infer_unit_from_column(y)
        unit_right = _infer_unit_from_column(y_right)
        style: dict[str, Any] = {"title": "Dual-axis Combo"}
        if unit_left or unit_right:
            style["units"] = {"left": unit_left or "", "right": unit_right or ""}
        return {
            "chart_type": "composed",
            "encoding": {"x": x, "y": y},
            "layers": [
                {"mark": "line", "encoding": {"x": x, "y": y}, "y_axis": "left", "alpha": 0.9},
                {"mark": "bar", "encoding": {"x": x, "y": y_right}, "y_axis": "right", "alpha": 0.5},
            ],
            "stats_overlay": {"enabled": False, "method": "auto"},
            "style": style,
        }

    return None


def _guess_simple_spec(message: str, columns: list[str]) -> dict[str, Any]:
    advanced = _guess_advanced_spec(message, columns)
    if advanced:
        return advanced

    lower = message.lower()
    chart_type = "scatter"
    if "箱线" in message or "box" in lower:
        chart_type = "box"
    elif "violin" in lower or "小提琴" in message:
        chart_type = "violin"
    elif "hist" in lower or "直方" in message:
        chart_type = "hist"
    elif "bar" in lower or "柱" in message:
        chart_type = "bar"
    elif "line" in lower or "折线" in message:
        chart_type = "line"
    elif "heat" in lower or "热图" in message or "相关" in message:
        chart_type = "heatmap"

    x = columns[0] if columns else None
    y = columns[1] if len(columns) > 1 else None

    if chart_type == "hist":
        return {"chart_type": "hist", "x": x, "title": "Histogram (fallback)"}

    if chart_type == "bar":
        return {"chart_type": "bar", "x": x, "y": y, "title": "Bar (fallback)"}

    if chart_type == "heatmap":
        return {"chart_type": "heatmap", "title": "Heatmap (fallback)"}

    return {
        "chart_type": chart_type,
        "x": x,
        "y": y,
        "title": f"{chart_type.title()} (fallback)",
    }


def _limit_trace(trace: list[str]) -> list[str]:
    return trace[:MAX_TRACE_STEPS]


def _extract_column_hint(message: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        hint = match.group(1).strip()
        hint = hint.strip(" ，。,:：;；()[]{}")
        if hint:
            return hint
    return None


def _infer_palette_from_message(message: str) -> str | None:
    lower = message.lower()
    explicit = re.search(
        r"(?:palette|调色板)\s*(?:改为|设为|=|:)\s*([A-Za-z][A-Za-z0-9_-]{1,32})",
        message,
        flags=re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1)

    for token, palette in PALETTE_KEYWORDS.items():
        if token in lower or token in message:
            return palette
    return None


def _detect_chart_type(message: str) -> str | None:
    lower = message.lower()
    if "箱线" in message or "box" in lower:
        return "box"
    if "小提琴" in message or "violin" in lower:
        return "violin"
    if "直方" in message or "hist" in lower:
        return "hist"
    if "柱状" in message or "柱形" in message or "bar" in lower:
        return "bar"
    if "折线" in message or "line" in lower:
        return "line"
    if "热图" in message or "heatmap" in lower or "相关" in message:
        return "heatmap"
    if "散点" in message or "scatter" in lower:
        return "scatter"
    return None


def _strip_quoted_text(text: str) -> str:
    out = text.strip().strip("，。；;")
    if (out.startswith('"') and out.endswith('"')) or (out.startswith("'") and out.endswith("'")):
        out = out[1:-1]
    return out.strip()


def _extract_title_from_message(message: str) -> tuple[bool, str | None]:
    if re.search(r"(取消标题|不要标题|无标题|title\s*(?:=|:)\s*(?:none|null))", message, flags=re.IGNORECASE):
        return True, None

    patterns = [
        r"(?:标题|title)\s*(?:改为|设为|设置为|=|:)\s*(.+)$",
        r"^(?:把|将)?(?:图|图表)?标题(?:改为|设为|设置为)?\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        title = _strip_quoted_text(match.group(1))
        if title:
            return True, title[:120]
    return False, None


def _extract_agg_override(message: str) -> tuple[bool, str | None]:
    lower = message.lower()
    if re.search(r"(取消聚合|不聚合|不要聚合|去掉聚合|agg\s*(?:=|:)\s*(?:none|null))", message, flags=re.IGNORECASE):
        return True, None

    explicit = re.search(
        r"(?:agg|聚合)\s*(?:改为|设为|设置为|=|:)\s*(mean|median|sum|count|avg|average)",
        message,
        flags=re.IGNORECASE,
    )
    if explicit:
        value = explicit.group(1).lower()
        if value in {"avg", "average"}:
            value = "mean"
        return True, value

    if "平均" in message or "均值" in message:
        return True, "mean"
    if "中位" in message:
        return True, "median"
    if "求和" in message or "总和" in message:
        return True, "sum"
    if "计数" in message or "频数" in message or "count" in lower:
        return True, "count"
    return False, None


def _extract_bins_override(message: str) -> tuple[bool, int | None]:
    if re.search(r"(取消分箱|不分箱|不要分箱|bins?\s*(?:=|:)\s*(?:none|null))", message, flags=re.IGNORECASE):
        return True, None

    match = re.search(r"(?:bins?|分箱)\s*(?:改为|设为|设置为|=|:)?\s*(\d{1,3})", message, flags=re.IGNORECASE)
    if not match:
        return False, None
    return True, int(match.group(1))


def _has_plot_intent(message: str, *, has_existing_spec: bool) -> bool:
    text = message.strip()
    if not text:
        return False
    lower = text.lower()
    for keyword in PLOT_INTENT_KEYWORDS:
        if keyword in text or keyword in lower:
            return True
    if has_existing_spec and EDIT_VERB_PATTERN.search(text):
        return True
    return False


def _is_explicit_plot_edit_request(message: str, *, has_existing_spec: bool) -> bool:
    if not has_existing_spec:
        return False
    if _detect_chart_type(message):
        return True
    if EDIT_VERB_PATTERN.search(message):
        return True
    if re.search(r"(x轴|y轴|横轴|纵轴|hue|调色板|palette|颜色|标题|title|agg|聚合|bins|分箱|facet|分面|双轴|回归|统计标注)", message, flags=re.IGNORECASE):
        return True
    return False


def _build_rule_spec_data(
    *,
    message: str,
    session: SessionData,
    columns: list[str],
    trace: list[str],
) -> dict[str, Any]:
    advanced = _guess_advanced_spec(message, columns)
    if advanced:
        trace.append("命中高级图模板，已生成 layers/facet 组合规范")
        return _apply_request_overrides(message, advanced, columns, trace)

    if session.last_plot_spec is not None:
        base = _spec_to_dict(session.last_plot_spec)
        trace.append("检测到已有 PlotSpec，基于当前图执行增量修改")
    else:
        base = _guess_simple_spec(message, columns)
        trace.append("未检测到已有 PlotSpec，使用规则模板初始化图表参数")

    return _apply_request_overrides(message, base, columns, trace)


def _apply_request_overrides(
    message: str,
    spec_data: dict[str, Any],
    columns: list[str],
    trace: list[str],
) -> dict[str, Any]:
    out = dict(spec_data)
    if not isinstance(out.get("layers"), list):
        out["layers"] = out.get("layers") if isinstance(out.get("layers"), list) else None

    def safe_resolve(name: str, field_name: str) -> str | None:
        try:
            return resolve_column_name(name, columns, field_name=field_name, notes=trace)
        except ValueError:
            trace.append(f"{field_name} 列名未找到：{name}，已忽略该覆写")
            return None

    def sync_layer_encoding(field: str, value: str | None) -> None:
        raw_layers = out.get("layers")
        if not isinstance(raw_layers, list):
            return
        for layer in raw_layers:
            if not isinstance(layer, dict):
                continue
            encoding = layer.get("encoding")
            if not isinstance(encoding, dict):
                encoding = {}
                layer["encoding"] = encoding
            if field == "hue":
                if value is None:
                    encoding.pop("hue", None)
                    encoding.pop("color", None)
                else:
                    encoding["hue"] = value
                    encoding["color"] = value
            else:
                if value is None:
                    encoding.pop(field, None)
                else:
                    encoding[field] = value

    chart_override = _detect_chart_type(message)
    keep_composed = (
        out.get("chart_type") == "composed"
        and isinstance(out.get("layers"), list)
        and len(out.get("layers") or []) > 1
        and bool(re.search(r"(组合|叠加|加|\+|＋|overlay|composed)", message, flags=re.IGNORECASE))
    )
    if chart_override and out.get("chart_type") != chart_override and not keep_composed:
        out["chart_type"] = chart_override
        if chart_override != "composed":
            out.pop("layers", None)
            out.pop("facet", None)
        trace.append(f"检测到显式图类型指令，切换为 {chart_override}")

    if re.search(r"(不要分组|取消分组|不分组|去掉分组)", message):
        out["hue"] = None
        sync_layer_encoding("hue", None)
        trace.append("按请求取消分组（hue=None）")
    else:
        group_hint = _extract_column_hint(
            message,
            [
                r"(?:按|根据)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})\s*(?:进行)?(?:分组|分色|着色|上色|分层)",
                r"(?:hue|分组列|颜色列|group(?:_by|by)?)\s*(?:改为|设为|=|:)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})",
            ],
        )
        if group_hint:
            resolved = safe_resolve(group_hint, "group")
            if resolved:
                out["hue"] = resolved
                sync_layer_encoding("hue", resolved)
                trace.append(f"分组列按用户指令设置为 {resolved}")

    x_hint = _extract_column_hint(
        message,
        [
            r"(?:x轴|横轴|x)\s*(?:改为|设为|=|:)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})",
        ],
    )
    if x_hint:
        resolved = safe_resolve(x_hint, "x")
        if resolved:
            out["x"] = resolved
            sync_layer_encoding("x", resolved)
            trace.append(f"x 轴按用户指令设置为 {resolved}")

    y_hint = _extract_column_hint(
        message,
        [
            r"(?:y轴|纵轴|y)\s*(?:改为|设为|=|:)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})",
        ],
    )
    if y_hint:
        resolved = safe_resolve(y_hint, "y")
        if resolved:
            out["y"] = resolved
            sync_layer_encoding("y", resolved)
            trace.append(f"y 轴按用户指令设置为 {resolved}")

    palette = _infer_palette_from_message(message)
    if palette:
        out["palette"] = palette
        trace.append(f"颜色方案按用户指令设置为 {palette}")

    has_title, next_title = _extract_title_from_message(message)
    if has_title:
        out["title"] = next_title
        trace.append(f"标题按用户指令更新为：{next_title or '(空)'}")

    has_agg, next_agg = _extract_agg_override(message)
    if has_agg:
        out["agg"] = next_agg
        trace.append(f"聚合方式按用户指令设置为：{next_agg or '(none)'}")

    has_bins, next_bins = _extract_bins_override(message)
    if has_bins:
        out["bins"] = next_bins
        trace.append(f"分箱参数按用户指令设置为：{next_bins if next_bins is not None else '(none)'}")

    if re.search(r"(取消分面|不分面|去掉分面)", message, flags=re.IGNORECASE):
        out["facet"] = None
        trace.append("按请求取消分面")
    else:
        facet_hint = _extract_column_hint(
            message,
            [
                r"(?:按|根据)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})\s*(?:分面|facet)",
                r"(?:facet|分面列)\s*(?:改为|设为|=|:)\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,40})",
            ],
        )
        if facet_hint:
            facet_col = safe_resolve(facet_hint, "facet")
            if facet_col:
                out["facet"] = {"field": facet_col, "columns": 3}
                trace.append(f"分面列按用户指令设置为 {facet_col}")

    if re.search(r"(统计标注|显著性|p值|p 值|效应量|effect size)", message, flags=re.IGNORECASE):
        out["stats_overlay"] = {"enabled": True, "method": "auto"}
        trace.append("按请求启用统计标注图层")
    if re.search(r"(关闭统计|不要统计标注|取消统计标注)", message, flags=re.IGNORECASE):
        out["stats_overlay"] = {"enabled": False, "method": "auto"}
        trace.append("按请求关闭统计标注图层")

    return out


def _spec_to_dict(spec: PlotSpec) -> dict[str, Any]:
    layers_payload = []
    for layer in spec.layers:
        layers_payload.append(
            {
                "mark": layer.mark,
                "encoding": dict(layer.encoding),
                "jitter": layer.jitter,
                "alpha": layer.alpha,
                "box_width": layer.box_width,
                "y_axis": layer.y_axis,
                "ci": layer.ci,
                "fit": layer.fit,
                "name": layer.name,
                **(layer.params or {}),
            }
        )

    return {
        "chart_type": spec.chart_type,
        "x": spec.x,
        "y": spec.y,
        "hue": spec.hue,
        "palette": spec.palette,
        "title": spec.title,
        "agg": spec.agg,
        "bins": spec.bins,
        "filters": [{"column": r.column, "op": r.op, "value": r.value} for r in spec.filters],
        "data_ref": spec.data_ref,
        "encoding": dict(spec.encoding),
        "layers": layers_payload,
        "facet": {"field": spec.facet.field, "columns": spec.facet.columns} if spec.facet else None,
        "stats_overlay": {"enabled": spec.stats_overlay.enabled, "method": spec.stats_overlay.method},
        "style": dict(spec.style),
    }


def _current_plot_context(session: SessionData, trace: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    if session.last_plot_spec is None:
        return None, None, None, []

    spec = session.last_plot_spec
    active = _active_df(session)
    warnings: list[str] = []

    try:
        stats = compute_pvalue(active, spec)
        plot_payload, payload_warnings = build_plot_payload(active, spec, precomputed_stats=stats)
        warnings.extend(payload_warnings)
        trace.append("沿用当前 PlotSpec 刷新图像状态")
        return _spec_to_dict(spec), plot_payload, stats, warnings
    except Exception as exc:
        warnings.append(f"当前 PlotSpec 无法在最新表格视图渲染：{exc}")
        trace.append("当前 PlotSpec 在最新数据视图上不可渲染，已保留参数等待修正")
        return _spec_to_dict(spec), None, None, warnings


def _validate_spec_or_400(spec_data: dict[str, Any], columns: list[str], trace: list[str]) -> PlotSpec:
    try:
        return validate_plot_spec(spec_data, columns, notes=trace)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid plot spec: {exc}") from exc


def _fallback_renderable_spec(spec: PlotSpec, columns: list[str], trace: list[str]) -> PlotSpec:
    if not columns:
        raise ValueError("No columns available for fallback rendering")

    x = spec.x if spec.x in columns else columns[0]
    y = spec.y if spec.y in columns and spec.y != x else (columns[1] if len(columns) > 1 and columns[1] != x else None)
    hue = spec.hue if spec.hue in columns and spec.hue not in {x, y} else None

    fallback_data: dict[str, Any]
    if x and y:
        fallback_data = {
            "chart_type": "scatter",
            "x": x,
            "y": y,
            "hue": hue,
            "palette": spec.palette,
            "title": spec.title or "Fallback Scatter",
            "filters": [{"column": r.column, "op": r.op, "value": r.value} for r in spec.filters],
        }
    else:
        fallback_data = {
            "chart_type": "hist",
            "x": x,
            "palette": spec.palette,
            "title": spec.title or "Fallback Histogram",
            "filters": [{"column": r.column, "op": r.op, "value": r.value} for r in spec.filters],
        }

    trace.append("构建降级 PlotSpec（基础可渲染形态）")
    return validate_plot_spec(fallback_data, columns, notes=trace)


def _build_chart_response(
    *,
    session_id: str,
    session: SessionData,
    spec: PlotSpec,
    summary: str,
    trace: list[str],
    used_fallback: bool,
    model_raw_text: str,
    include_legacy_render: bool,
) -> dict[str, Any]:
    df = _active_df(session)
    warnings: list[str] = []
    stats = compute_pvalue(df, spec)
    try:
        plot_payload, payload_warnings = build_plot_payload(df, spec, precomputed_stats=stats)
        warnings.extend(payload_warnings)
    except Exception as exc:
        warnings.append(f"高级图渲染失败，已自动降级：{exc}")
        trace.append(f"原始 PlotSpec 渲染失败，准备降级：{exc}")
        try:
            degraded_spec = _fallback_renderable_spec(spec, [str(c) for c in df.columns], trace)
            stats = compute_pvalue(df, degraded_spec)
            plot_payload, payload_warnings = build_plot_payload(df, degraded_spec, precomputed_stats=stats)
            warnings.extend(payload_warnings)
            spec = degraded_spec
            trace.append("降级渲染成功")
        except Exception as degrade_exc:
            raise HTTPException(status_code=400, detail=f"Failed to render plot payload: {degrade_exc}") from degrade_exc

    if stats:
        trace.append(
            f"统计检验完成：method={stats['method']}, p={stats['p_value']:.4g}"
        )
    else:
        trace.append("当前图形与数据条件不满足 p 值计算，已跳过")

    legacy_image_b64 = ""
    if include_legacy_render:
        legacy_image_b64, _, _ = render_plot(df, spec)
        trace.append("已生成 legacy 后端图像（fallback 模式）")

    return {
        "session_id": session_id,
        "summary": summary,
        "used_fallback": used_fallback,
        "plot_spec": _spec_to_dict(spec),
        "stats": stats,
        "warnings": warnings,
        "thinking": _limit_trace(trace),
        "table_state": _table_state(session),
        "plot_payload": plot_payload,
        "legacy_image_base64": legacy_image_b64,
        "raw_model_text": model_raw_text[:2000],
    }


def _safe_pdf_name(raw_name: str | None) -> str:
    base = (raw_name or "chart").strip()
    if not base:
        base = "chart"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base[:80].strip("._-")
    if not base:
        base = "chart"
    if not base.lower().endswith(".pdf"):
        base = f"{base}.pdf"
    return base


def _general_chat_reply(message: str, *, has_dataset: bool) -> tuple[str, bool]:
    cfg = load_config()

    system_prompt = (
        "You are a concise Chinese data assistant. "
        "Answer the user's question directly in Chinese. "
        "If the user asks for plotting and no dataset is available, "
        "tell them they can load a local Excel/CSV by chat command like: "
        "加载文件 /home/zhang/data.csv."
    )

    try:
        text = call_responses_api(
            api_key=cfg.api_key or "",
            model_cfg=cfg.model,
            system_prompt=system_prompt,
            user_prompt=message,
        )
        cleaned = (text or "").strip()
        if cleaned:
            return cleaned, False
    except Exception:
        pass

    if has_dataset:
        fallback = "已收到你的消息。当前已加载数据，你可以继续提问，或直接要求我调整图表参数。"
    else:
        fallback = (
            "已收到你的消息。当前未检测到已上传数据，可先继续聊天；"
            "如果要基于表格绘图，可直接在聊天输入：加载文件 /home/zhang/xxx.csv。"
        )
    return fallback, True


@app.post("/api/chat")
def chat_and_plot(request: ChatRequest) -> dict[str, Any]:
    trace: list[str] = ["收到用户请求，开始解析"]
    session_id = request.session_id or uuid.uuid4().hex
    session = SESSIONS.get(session_id)

    table_command = _table_command_from_message(request.message)
    if table_command:
        trace.append(f"识别为表格控制指令：{table_command.get('action')}")
        summary, updated_session, preview_rows = _execute_table_command(
            command=table_command,
            session_id=session_id,
            session=session,
            trace=trace,
        )
        table_payload = _table_state(updated_session, preview_rows=preview_rows) if updated_session else None
        plot_spec_payload: dict[str, Any] | None = None
        plot_payload: dict[str, Any] | None = None
        stats: dict[str, Any] | None = None
        warnings: list[str] = []
        if updated_session:
            plot_spec_payload, plot_payload, stats, warnings = _current_plot_context(updated_session, trace)
        return {
            "session_id": session_id,
            "summary": summary,
            "used_fallback": False,
            "plot_spec": plot_spec_payload,
            "stats": stats,
            "warnings": warnings,
            "thinking": _limit_trace(trace),
            "table_state": table_payload,
            "plot_payload": plot_payload,
            "legacy_image_base64": "",
            "raw_model_text": "",
        }

    session = SESSIONS.get(session_id)
    if not session:
        trace.append("未检测到已上传表格，进入通用对话模式")
        summary, used_fallback = _general_chat_reply(request.message, has_dataset=False)
        return {
            "session_id": session_id,
            "summary": summary,
            "used_fallback": used_fallback,
            "plot_spec": None,
            "stats": None,
            "warnings": [],
            "thinking": _limit_trace(trace),
            "table_state": None,
            "plot_payload": None,
            "legacy_image_base64": "",
            "raw_model_text": "",
        }

    df = _active_df(session)
    columns = [str(c) for c in df.columns]
    trace.append(
        f"已载入数据：{session.filename}，当前视图 {len(df)} 行 / 原始 {len(session.df)} 行，{len(columns)} 列"
    )

    has_existing_spec = session.last_plot_spec is not None
    if not _has_plot_intent(request.message, has_existing_spec=has_existing_spec):
        trace.append("识别为通用对话，不触发图表规划")
        summary, used_fallback = _general_chat_reply(request.message, has_dataset=True)
        current_spec, current_plot_payload, current_stats, current_warnings = _current_plot_context(session, trace)
        return {
            "session_id": session_id,
            "summary": summary,
            "used_fallback": used_fallback,
            "plot_spec": current_spec,
            "stats": current_stats,
            "warnings": current_warnings,
            "thinking": _limit_trace(trace),
            "table_state": _table_state(session),
            "plot_payload": current_plot_payload,
            "legacy_image_base64": "",
            "raw_model_text": "",
        }

    sample_rows = (
        df.head(20)
        .where(pd.notnull(df.head(20)), None)
        .to_dict(orient="records")
    )

    cfg = load_config()
    explicit_edit = _is_explicit_plot_edit_request(request.message, has_existing_spec=has_existing_spec)
    template_spec = _guess_advanced_spec(request.message, columns)
    used_fallback = False
    used_rule_engine = False
    model_raw_text = ""

    if template_spec:
        trace.append("检测到高级图模板指令，直接生成 composed PlotSpec")
        spec_data = _apply_request_overrides(request.message, template_spec, columns, trace)
        used_rule_engine = True
    elif explicit_edit:
        trace.append("识别为图表参数编辑指令，优先基于当前 PlotSpec 执行规则修改")
        spec_data = _build_rule_spec_data(
            message=request.message,
            session=session,
            columns=columns,
            trace=trace,
        )
        used_rule_engine = True
    else:
        system_prompt = (
            "You are a data visualization planner. "
            "Return JSON only, no markdown. "
            "Allowed chart_type: scatter,line,bar,hist,box,violin,heatmap,composed. "
            "For advanced requests, prefer chart_type=composed with layers and optional facet. "
            "Supported layer marks: scatter,line,bar,hist,boxplot,violin,regression. "
            "Only use provided columns. "
            "Respect explicit user edits for color/grouping/axis. "
            "If user asks to change grouping, update hue/x accordingly. "
            "If user asks to change color, set palette accordingly. "
            "Output schema: "
            "{chart_type,data_ref,encoding,layers,facet,stats_overlay,style,x,y,hue,palette,title,agg,bins,filters:[{column,op,value}]}. "
            "Example advanced: scatter + boxplot layers with stats_overlay enabled."
        )

        current_spec = _spec_to_dict(session.last_plot_spec) if session.last_plot_spec else None
        user_prompt = (
            f"User request: {request.message}\n"
            f"Current plot spec: {current_spec}\n"
            f"Columns: {columns}\n"
            f"Sample rows: {sample_rows}"
        )

        if not cfg.api_key:
            trace.append("未配置 OPENAI_API_KEY，改用规则引擎生成 PlotSpec")
            spec_data = _build_rule_spec_data(
                message=request.message,
                session=session,
                columns=columns,
                trace=trace,
            )
            used_fallback = True
            used_rule_engine = True
        else:
            try:
                trace.append("调用模型生成绘图结构化规范")
                model_raw_text = call_responses_api(
                    api_key=cfg.api_key,
                    model_cfg=cfg.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                spec_data = parse_json_from_model_output(model_raw_text)
                trace.append("模型规范解析成功")
            except Exception as exc:
                trace.append(f"模型不可用或输出不可解析，改用规则引擎：{exc.__class__.__name__}")
                spec_data = _build_rule_spec_data(
                    message=request.message,
                    session=session,
                    columns=columns,
                    trace=trace,
                )
                used_fallback = True
                used_rule_engine = True

    if not used_rule_engine:
        spec_data = _apply_request_overrides(request.message, spec_data, columns, trace)
    spec = _validate_spec_or_400(spec_data, columns, trace)
    session.last_plot_spec = spec
    trace.append(
        f"规范校验通过：chart={spec.chart_type}, x={spec.x}, y={spec.y}, hue={spec.hue}, palette={spec.palette}"
    )

    if explicit_edit:
        response_summary = f"已按指令更新当前图表参数（{spec.chart_type}）。"
    elif used_fallback:
        response_summary = f"模型暂不可用，已通过规则引擎生成 {spec.chart_type} 图。"
    else:
        response_summary = f"已按请求生成 {spec.chart_type} 图。"

    return _build_chart_response(
        session_id=session_id,
        session=session,
        spec=spec,
        summary=response_summary,
        trace=trace,
        used_fallback=used_fallback,
        model_raw_text=model_raw_text,
        include_legacy_render=cfg.model.enable_legacy_backend_render,
    )


@app.post("/api/plot/spec")
def preview_spec(request: SpecRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    trace = ["收到手动编辑的 PlotSpec，开始校验与预览"]
    active = _active_df(session)
    columns = [str(c) for c in active.columns]
    spec = _validate_spec_or_400(request.plot_spec, columns, trace)
    session.last_plot_spec = spec
    trace.append("PlotSpec 校验通过")

    return _build_chart_response(
        session_id=request.session_id,
        session=session,
        spec=spec,
        summary=f"已根据编辑后的 PlotSpec 重新生成 {spec.chart_type} 图预览数据。",
        trace=trace,
        used_fallback=False,
        model_raw_text="",
        include_legacy_render=False,
    )


@app.post("/api/stats")
def compute_stats(request: SpecRequest) -> dict[str, Any]:
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    active = _active_df(session)
    columns = [str(c) for c in active.columns]
    trace: list[str] = []
    spec = _validate_spec_or_400(request.plot_spec, columns, trace)
    stats = compute_pvalue(active, spec)
    return {
        "session_id": request.session_id,
        "plot_spec": _spec_to_dict(spec),
        "stats": stats,
        "warnings": trace,
    }


@app.post("/api/export/pdf")
def export_pdf(request: ExportPdfRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    active = _active_df(session)
    columns = [str(c) for c in active.columns]
    trace: list[str] = []
    spec = _validate_spec_or_400(request.plot_spec, columns, trace)

    try:
        _, pdf_b64, _ = render_plot(active, spec)
        pdf_bytes = base64.b64decode(pdf_b64.encode("ascii"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF export failed: {exc}") from exc

    download_name = _safe_pdf_name(request.filename)
    headers = {"Content-Disposition": f'attachment; filename="{download_name}"'}
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@app.get("/")
def index() -> FileResponse:
    for base_dir in _frontend_base_dirs():
        index_file = base_dir / "index.html"
        if index_file.exists() and index_file.is_file():
            return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Frontend index not found")


@app.get("/{path:path}")
def static_fallback(path: str):
    clean = path.lstrip("/")
    for base_dir in _frontend_base_dirs():
        if base_dir.resolve() == ROOT_DIR.resolve() and clean not in LEGACY_STATIC_FILES:
            continue
        candidate = _safe_join(base_dir, path)
        if candidate and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="Not Found")


def _frontend_base_dirs() -> list[Path]:
    if FRONTEND_DIST_DIR.exists():
        return [FRONTEND_DIST_DIR]
    return [ROOT_DIR]


def _safe_join(base: Path, user_path: str) -> Path | None:
    clean = user_path.lstrip("/")
    candidate = (base / clean).resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate
