from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

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
MAX_CELL_RANGE_UPDATES = 10_000
MAX_UNDO_STEPS = 80
MAX_SNAPSHOT_COUNT = 30
MAX_SNAPSHOT_NAME_LEN = 40
MAX_PLOT_MESSAGE_CACHE = 80
DEFAULT_SHEET_ROWS = 50
DEFAULT_SHEET_COLS = 8
MAX_SCRATCH_ROWS = 20_000
MAX_SCRATCH_COLS = 512
MAX_SESSION_HISTORY = 200
TABLE_OPS = {"==", "!=", ">", ">=", "<", "<=", "in", "not in"}
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
    "stats",
    "chart_type",
    "x=",
    "y=",
    "hue=",
    "type=",
    "raincloud",
)
EDIT_VERB_PATTERN = re.compile(
    r"(改成|改为|改一下|调整|设为|设置为|变成|切换|取消|去掉|不要|change|set|update|remove)",
    flags=re.IGNORECASE,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class SessionData:
    df: pd.DataFrame
    filename: str
    view_df: pd.DataFrame | None = None
    last_plot_spec: PlotSpec | None = None
    undo_stack: list[dict[str, Any]] = field(default_factory=list)
    redo_stack: list[dict[str, Any]] = field(default_factory=list)
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    plot_message_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_plot_fingerprint: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    history: list[dict[str, Any]] = field(default_factory=list)


SESSIONS: dict[str, SessionData] = {}


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, min_length=8, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["auto", "chat", "plot", "table"] = Field(default="auto")


class SpecRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)
    plot_spec: dict[str, Any]


class ExportPdfRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)
    plot_spec: dict[str, Any]
    filename: str | None = Field(default=None, max_length=120)


class ExportCsvRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)
    filename: str | None = Field(default=None, max_length=120)
    source: Literal["active", "original"] = Field(default="active")


app = FastAPI(title="SheetPilot Studio", version="0.1.0")

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


def _append_session_history(
    session: SessionData,
    *,
    action: str,
    summary: str,
    details: dict[str, Any] | None = None,
) -> None:
    normalized_details: dict[str, Any]
    if details:
        try:
            normalized_details = json.loads(json.dumps(details, default=str))
        except Exception:
            normalized_details = {"raw": str(details)}
    else:
        normalized_details = {}

    item = {
        "ts": _utc_now_iso(),
        "action": str(action).strip()[:64] or "event",
        "summary": str(summary).strip()[:300] or "event",
        "details": normalized_details,
    }
    session.history.append(item)
    if len(session.history) > MAX_SESSION_HISTORY:
        session.history = session.history[-MAX_SESSION_HISTORY:]
    session.updated_at = item["ts"]


def _capture_table_snapshot(session: SessionData) -> dict[str, Any]:
    return {
        "df": session.df.copy(deep=True),
        "view_df": session.view_df.copy(deep=True) if session.view_df is not None else None,
    }


def _restore_table_snapshot(session: SessionData, snapshot: dict[str, Any]) -> None:
    snapshot_df = snapshot.get("df")
    if not isinstance(snapshot_df, pd.DataFrame):
        raise ValueError("invalid snapshot")
    snapshot_view = snapshot.get("view_df")
    if snapshot_view is not None and not isinstance(snapshot_view, pd.DataFrame):
        raise ValueError("invalid snapshot view")
    session.df = snapshot_df.copy(deep=True)
    session.view_df = snapshot_view.copy(deep=True) if snapshot_view is not None else None


def _push_undo_snapshot(session: SessionData) -> None:
    session.undo_stack.append(_capture_table_snapshot(session))
    if len(session.undo_stack) > MAX_UNDO_STEPS:
        session.undo_stack = session.undo_stack[-MAX_UNDO_STEPS:]
    session.redo_stack.clear()


def _normalize_snapshot_name(raw_name: str) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return ""
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "", name)
    name = name[:MAX_SNAPSHOT_NAME_LEN].strip("._-")
    return name


def _save_named_snapshot(session: SessionData, raw_name: str) -> str:
    name = _normalize_snapshot_name(raw_name)
    if not name:
        raise ValueError("快照名称不能为空，且仅支持中英文、数字、下划线和连字符。")

    session.snapshots[name] = {
        "saved_at": _utc_now_iso(),
        "table": _capture_table_snapshot(session),
        "rows": int(len(_active_df(session))),
        "source_rows": int(len(session.df)),
    }
    while len(session.snapshots) > MAX_SNAPSHOT_COUNT:
        oldest = next(iter(session.snapshots.keys()))
        session.snapshots.pop(oldest, None)
    return name


def _load_named_snapshot(session: SessionData, raw_name: str) -> str:
    name = _normalize_snapshot_name(raw_name)
    if not name:
        raise ValueError("快照名称不能为空。")
    data = session.snapshots.get(name)
    if not data:
        raise ValueError(f"未找到快照：{name}")

    table = data.get("table")
    if not isinstance(table, dict):
        raise ValueError(f"快照损坏：{name}")
    _restore_table_snapshot(session, table)
    return name


def _normalize_plot_message_key(message: str) -> str:
    normalized = re.sub(r"\s+", " ", message.strip().lower())
    return normalized[:400]


def _trim_plot_cache(cache: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if len(cache) <= MAX_PLOT_MESSAGE_CACHE:
        return cache
    keys = list(cache.keys())[-MAX_PLOT_MESSAGE_CACHE:]
    return {key: cache[key] for key in keys}


def _spec_fingerprint(spec_data: dict[str, Any]) -> str:
    try:
        canonical = json.dumps(spec_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        canonical = str(spec_data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def _parse_filter_values(raw: str) -> list[Any]:
    text = raw.strip().strip("，。")
    if not text:
        return []

    candidate = text
    if candidate[0] in "[(" and candidate[-1] in "])":
        try:
            parsed = ast.literal_eval(candidate)
            if isinstance(parsed, (list, tuple, set)):
                return list(parsed)
        except Exception:
            candidate = candidate[1:-1].strip()

    if "," in candidate or "，" in candidate:
        parts = re.split(r"[，,]", candidate)
        return [_parse_scalar_value(part) for part in parts if part.strip()]

    scalar = _parse_scalar_value(candidate)
    return [] if scalar == "" else [scalar]


def _parse_numeric_scalar(raw: str) -> float | None:
    value = _parse_scalar_value(raw)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_cell_value_for_series(value: Any, series: pd.Series) -> Any:
    if value is None:
        return None

    if pd.api.types.is_numeric_dtype(series) and not isinstance(value, bool):
        return pd.to_numeric(pd.Series([value]), errors="raise").iloc[0]

    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(pd.Series([value]), errors="raise").iloc[0]

    return value


def _parse_human_index(raw: str) -> int | None:
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100}
    if not re.fullmatch(r"[零〇一二两三四五六七八九十百]+", text):
        return None

    total = 0
    current = 0
    for ch in text:
        if ch in digit_map:
            current = digit_map[ch]
            continue
        if ch in unit_map:
            unit = unit_map[ch]
            if current == 0:
                current = 1
            total += current * unit
            current = 0
            continue
    return total + current


def _excel_col_to_index(raw: str) -> int | None:
    text = str(raw or "").strip()
    if not re.fullmatch(r"[A-Za-z]{1,4}", text):
        return None
    index = 0
    for ch in text.upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def _parse_excel_cell_ref(raw: str) -> tuple[int, int] | None:
    text = str(raw or "").strip()
    match = re.fullmatch(r"([A-Za-z]{1,4})(\d{1,7})", text)
    if not match:
        return None
    col = _excel_col_to_index(match.group(1))
    row = int(match.group(2))
    if col is None or row < 1:
        return None
    return row, col


def _excel_col_label(index: int) -> str:
    if index < 1:
        raise ValueError("column index must be >= 1")
    chars: list[str] = []
    value = index
    while value > 0:
        value, rem = divmod(value - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def _scratch_sheet_shape_from_command(command: dict[str, Any]) -> tuple[int, int, str | None]:
    action = command.get("action")
    requested_rows = DEFAULT_SHEET_ROWS
    requested_cols = DEFAULT_SHEET_COLS

    if action == "update_cell":
        requested_rows = max(requested_rows, int(command.get("row", 1)))
        if command.get("column_index") is not None:
            requested_cols = max(requested_cols, int(command.get("column_index", 1)))
    elif action == "update_cell_range":
        start = int(command.get("row_start", 1))
        end = int(command.get("row_end", 1))
        requested_rows = max(requested_rows, start, end)
        if command.get("column_index") is not None:
            requested_cols = max(requested_cols, int(command.get("column_index", 1)))

    if requested_rows < 1 or requested_cols < 1:
        return 0, 0, "单元格修改失败：行列索引必须从 1 开始。"
    if requested_rows > MAX_SCRATCH_ROWS:
        return 0, 0, f"单元格修改失败：空白表最多支持 {MAX_SCRATCH_ROWS} 行。"
    if requested_cols > MAX_SCRATCH_COLS:
        return 0, 0, f"单元格修改失败：空白表最多支持 {MAX_SCRATCH_COLS} 列。"
    return requested_rows, requested_cols, None


def _create_scratch_session(rows: int, cols: int) -> SessionData:
    columns = [_excel_col_label(i + 1) for i in range(cols)]
    data = {name: [None] * rows for name in columns}
    df = pd.DataFrame(data)
    return SessionData(df=df, filename="untitled_sheet", view_df=df.copy(), last_plot_spec=None)


def _table_command_from_message(message: str) -> dict[str, Any] | None:
    text = message.strip()
    if not text:
        return None

    save_snapshot_match = re.match(
        r"^(?:保存快照|保存版本|snapshot\s+save)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,60})$",
        text,
        flags=re.IGNORECASE,
    )
    if save_snapshot_match:
        return {"action": "save_snapshot", "name": save_snapshot_match.group(1).strip()}

    load_snapshot_match = re.match(
        r"^(?:加载快照|恢复快照|加载版本|snapshot\s+load)\s+([A-Za-z0-9_\-\u4e00-\u9fff]{1,60})$",
        text,
        flags=re.IGNORECASE,
    )
    if load_snapshot_match:
        return {"action": "load_snapshot", "name": load_snapshot_match.group(1).strip()}

    if re.match(r"^(?:查看快照|列出快照|snapshots?|snapshot\s+list)$", text, flags=re.IGNORECASE):
        return {"action": "list_snapshots"}

    if re.match(r"^(?:撤销|undo)$", text, flags=re.IGNORECASE):
        return {"action": "undo"}

    if re.match(r"^(?:重做|redo)$", text, flags=re.IGNORECASE):
        return {"action": "redo"}

    for pattern in [
        r"^(?:加载|导入|打开|读取)\s*(?:文件|数据集|dataset)?\s*[:：]?\s*(.+)$",
        r"^(?:load|open|read)\s+(?:file|dataset)?\s*[:=]?\s*(.+)$",
    ]:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"action": "load_file", "path": match.group(1).strip()}

    if re.match(r"^.+\.(?:csv|xlsx|xls)$", text, flags=re.IGNORECASE):
        return {"action": "load_file", "path": text}

    clip_group_range_cn = re.match(
        r"^把\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*中(?:的)?\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*组(?:的)?所有\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*的范围(?:更改|改为|限制|裁剪)为\s*([+-]?\d+(?:\.\d+)?)\s*(?:-|~|～|到)\s*([+-]?\d+(?:\.\d+)?)$",
        text,
        flags=re.IGNORECASE,
    )
    if clip_group_range_cn:
        lower = _parse_numeric_scalar(clip_group_range_cn.group(4))
        upper = _parse_numeric_scalar(clip_group_range_cn.group(5))
        if lower is not None and upper is not None:
            return {
                "action": "clip_group_range",
                "group_column": clip_group_range_cn.group(1).strip(),
                "group_value": _parse_scalar_value(clip_group_range_cn.group(2)),
                "target_column": clip_group_range_cn.group(3).strip(),
                "lower": lower,
                "upper": upper,
            }

    clip_group_range_en = re.match(
        r"^clip\s+([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s+where\s+([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s*==\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s+to\s+([+-]?\d+(?:\.\d+)?)\s*(?:-|~|～|to)\s*([+-]?\d+(?:\.\d+)?)$",
        text,
        flags=re.IGNORECASE,
    )
    if clip_group_range_en:
        lower = _parse_numeric_scalar(clip_group_range_en.group(4))
        upper = _parse_numeric_scalar(clip_group_range_en.group(5))
        if lower is not None and upper is not None:
            return {
                "action": "clip_group_range",
                "group_column": clip_group_range_en.group(2).strip(),
                "group_value": _parse_scalar_value(clip_group_range_en.group(3)),
                "target_column": clip_group_range_en.group(1).strip(),
                "lower": lower,
                "upper": upper,
            }

    set_cell_range_cn = re.match(
        r"^(?:把|将)?\s*第?\s*([0-9零〇一二两三四五六七八九十百]{1,8})\s*(?:到|-|~|～)\s*([0-9零〇一二两三四五六七八九十百]{1,8})\s*行\s*第?\s*([0-9零〇一二两三四五六七八九十百]{1,6})\s*列(?:的值)?\s*(?:改成|改为|设为|设置为|=)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_range_cn:
        row_start = _parse_human_index(set_cell_range_cn.group(1))
        row_end = _parse_human_index(set_cell_range_cn.group(2))
        col = _parse_human_index(set_cell_range_cn.group(3))
        if row_start is not None and row_end is not None and col is not None:
            return {
                "action": "update_cell_range",
                "row_start": row_start,
                "row_end": row_end,
                "column_index": col,
                "value": _parse_scalar_value(set_cell_range_cn.group(4)),
            }

    set_cell_range_en = re.match(
        r"^set\s+rows?\s+(\d{1,7})\s*(?:to|-)\s*(\d{1,7})\s+(?:col|column)\s+(\d{1,4})\s+to\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_range_en:
        return {
            "action": "update_cell_range",
            "row_start": int(set_cell_range_en.group(1)),
            "row_end": int(set_cell_range_en.group(2)),
            "column_index": int(set_cell_range_en.group(3)),
            "value": _parse_scalar_value(set_cell_range_en.group(4)),
        }

    set_cell_by_ref_cn = re.match(
        r"^(?:把|将)?\s*([A-Za-z]{1,4}\d{1,7})\s*(?:单元格)?(?:的值)?\s*(?:改成|改为|设为|设置为|=)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_ref_cn:
        parsed = _parse_excel_cell_ref(set_cell_by_ref_cn.group(1))
        if parsed is not None:
            row, col = parsed
            return {
                "action": "update_cell",
                "row": row,
                "column_index": col,
                "value": _parse_scalar_value(set_cell_by_ref_cn.group(2)),
            }

    set_cell_by_ref_en = re.match(
        r"^(?:set|update)\s+(?:cell\s+)?([A-Za-z]{1,4}\d{1,7})\s*(?:to|=)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_ref_en:
        parsed = _parse_excel_cell_ref(set_cell_by_ref_en.group(1))
        if parsed is not None:
            row, col = parsed
            return {
                "action": "update_cell",
                "row": row,
                "column_index": col,
                "value": _parse_scalar_value(set_cell_by_ref_en.group(2)),
            }

    set_cell_by_index_cn = re.match(
        r"^(?:把|将)?\s*第?\s*([0-9零〇一二两三四五六七八九十百]{1,8})\s*行\s*第?\s*([0-9零〇一二两三四五六七八九十百]{1,6})\s*列(?:的值)?\s*(?:改成|改为|设为|设置为|=)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_index_cn:
        row = _parse_human_index(set_cell_by_index_cn.group(1))
        col = _parse_human_index(set_cell_by_index_cn.group(2))
        if row is not None and col is not None:
            return {
                "action": "update_cell",
                "row": row,
                "column_index": col,
                "value": _parse_scalar_value(set_cell_by_index_cn.group(3)),
            }

    set_cell_by_name_cn = re.match(
        r"^(?:把|将)?\s*第?\s*([0-9零〇一二两三四五六七八九十百]{1,8})\s*行\s*([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})(?:列)?(?:的值)?\s*(?:改成|改为|设为|设置为|=)\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_name_cn:
        row = _parse_human_index(set_cell_by_name_cn.group(1))
        if row is not None:
            return {
                "action": "update_cell",
                "row": row,
                "column": set_cell_by_name_cn.group(2).strip(),
                "value": _parse_scalar_value(set_cell_by_name_cn.group(3)),
            }

    set_cell_by_index_en = re.match(
        r"^set\s+row\s+(\d{1,7})\s+(?:col|column)\s+(\d{1,4})\s+to\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_index_en:
        return {
            "action": "update_cell",
            "row": int(set_cell_by_index_en.group(1)),
            "column_index": int(set_cell_by_index_en.group(2)),
            "value": _parse_scalar_value(set_cell_by_index_en.group(3)),
        }

    set_cell_by_name_en = re.match(
        r"^set\s+row\s+(\d{1,7})\s+column\s+([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60})\s+to\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if set_cell_by_name_en:
        return {
            "action": "update_cell",
            "row": int(set_cell_by_name_en.group(1)),
            "column": set_cell_by_name_en.group(2).strip(),
            "value": _parse_scalar_value(set_cell_by_name_en.group(3)),
        }

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

    filter_in_match = re.match(
        r"^(?:筛选|过滤|filter)\s+([A-Za-z0-9_\u4e00-\u9fff\-\s()（）]{1,60}?)\s+(not\s+in|in)\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if filter_in_match:
        op = re.sub(r"\s+", " ", filter_in_match.group(2).lower()).strip()
        return {
            "action": "filter",
            "column": filter_in_match.group(1).strip(),
            "op": op,
            "value": _parse_filter_values(filter_in_match.group(3)),
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
    op = re.sub(r"\s+", " ", str(op).strip().lower())
    if op == "=":
        op = "=="
    if op not in TABLE_OPS:
        raise ValueError(f"不支持的操作符：{op}")

    series = df[column]
    if op in {"in", "not in"}:
        targets = list(value) if isinstance(value, (list, tuple, set)) else [value]
        if pd.api.types.is_numeric_dtype(series):
            converted_targets = []
            for target in targets:
                if target is None or isinstance(target, bool):
                    converted_targets.append(target)
                    continue
                converted_targets.append(pd.to_numeric(pd.Series([target]), errors="raise").iloc[0])
            targets = converted_targets
        mask = series.isin(targets)
        return df[~mask] if op == "not in" else df[mask]

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


def _resolve_update_column(
    command: dict[str, Any],
    columns: list[str],
    trace: list[str],
) -> tuple[str | None, int | None, str | None]:
    if command.get("column_index") is not None:
        column_number = int(command.get("column_index", 0))
        if column_number < 1 or column_number > len(columns):
            return None, None, f"单元格修改失败：第 {column_number} 列超出范围（当前共有 {len(columns)} 列）。"
        return columns[column_number - 1], column_number, None

    requested = str(command.get("column", "")).strip()
    if not requested:
        return None, None, "单元格修改失败：未提供列名。"
    try:
        resolved = resolve_column_name(requested, columns, field_name="update_cell", notes=trace)
    except ValueError:
        return None, None, f"单元格修改失败：未找到列 {requested}。"
    if not resolved:
        return None, None, "单元格修改失败：未提供有效列名。"
    return resolved, columns.index(resolved) + 1, None


def _resolve_column_with_error(
    requested: str,
    *,
    columns: list[str],
    field_name: str,
    trace: list[str],
    err_prefix: str,
) -> tuple[str | None, str | None]:
    target = requested.strip()
    if not target:
        return None, f"{err_prefix}：缺少列名。"
    try:
        resolved = resolve_column_name(target, columns, field_name=field_name, notes=trace)
    except ValueError:
        return None, f"{err_prefix}：未找到列 {target}。"
    if not resolved:
        return None, f"{err_prefix}：缺少有效列名。"
    return resolved, None


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
        _append_session_history(
            loaded,
            action="load_file",
            summary=f"通过聊天加载文件 {path.name}",
            details={"rows": int(len(df)), "columns": int(len(df.columns))},
        )
        SESSIONS[session_id] = loaded
        trace.append(f"已通过 chat 加载文件：{path}")
        return (
            f"已加载文件 {path.name}，共 {len(df)} 行 {len(df.columns)} 列。现在可直接要求绘图或继续筛选数据。",
            loaded,
            preview_rows,
        )

    if not session and action in {"update_cell", "update_cell_range"}:
        rows, cols, err = _scratch_sheet_shape_from_command(command)
        if err:
            return (err, None, preview_rows)
        session = _create_scratch_session(rows, cols)
        _append_session_history(
            session,
            action="create_scratch",
            summary="自动创建空白工作表",
            details={"rows": rows, "columns": cols},
        )
        SESSIONS[session_id] = session
        trace.append(f"未检测到已加载数据，已自动创建空白工作表：rows={rows}, cols={cols}")

    if not session:
        return (
            "当前还没有可操作的数据。你可以直接在聊天里输入：`加载文件 /home/zhang/xxx.csv`。",
            None,
            preview_rows,
        )

    if action == "undo":
        if not session.undo_stack:
            return ("当前没有可撤销操作。", session, preview_rows)
        current = _capture_table_snapshot(session)
        target = session.undo_stack.pop()
        session.redo_stack.append(current)
        if len(session.redo_stack) > MAX_UNDO_STEPS:
            session.redo_stack = session.redo_stack[-MAX_UNDO_STEPS:]
        _restore_table_snapshot(session, target)
        _append_session_history(
            session,
            action="undo",
            summary="撤销上一步表格操作",
            details={"undo_left": len(session.undo_stack), "redo_count": len(session.redo_stack)},
        )
        trace.append(f"撤销成功：undo_left={len(session.undo_stack)}, redo_count={len(session.redo_stack)}")
        return ("已撤销上一步操作。", session, preview_rows)

    if action == "redo":
        if not session.redo_stack:
            return ("当前没有可重做操作。", session, preview_rows)
        current = _capture_table_snapshot(session)
        target = session.redo_stack.pop()
        session.undo_stack.append(current)
        if len(session.undo_stack) > MAX_UNDO_STEPS:
            session.undo_stack = session.undo_stack[-MAX_UNDO_STEPS:]
        _restore_table_snapshot(session, target)
        _append_session_history(
            session,
            action="redo",
            summary="重做上一步表格操作",
            details={"undo_count": len(session.undo_stack), "redo_left": len(session.redo_stack)},
        )
        trace.append(f"重做成功：undo_count={len(session.undo_stack)}, redo_left={len(session.redo_stack)}")
        return ("已重做上一步操作。", session, preview_rows)

    if action == "save_snapshot":
        raw_name = str(command.get("name", ""))
        try:
            snapshot_name = _save_named_snapshot(session, raw_name)
        except ValueError as exc:
            return (f"快照保存失败：{exc}", session, preview_rows)
        _append_session_history(
            session,
            action="save_snapshot",
            summary=f"保存快照 {snapshot_name}",
            details={"snapshot": snapshot_name, "total_snapshots": len(session.snapshots)},
        )
        trace.append(f"已保存快照：{snapshot_name}")
        return (f"已保存快照：{snapshot_name}。", session, preview_rows)

    if action == "load_snapshot":
        requested_name = str(command.get("name", ""))
        snapshot_name = _normalize_snapshot_name(requested_name)
        if not snapshot_name:
            return ("快照加载失败：快照名称不能为空。", session, preview_rows)
        if snapshot_name not in session.snapshots:
            return (f"快照加载失败：未找到快照 {snapshot_name}。", session, preview_rows)
        _push_undo_snapshot(session)
        try:
            loaded_name = _load_named_snapshot(session, snapshot_name)
        except ValueError as exc:
            if session.undo_stack:
                session.undo_stack.pop()
            return (f"快照加载失败：{exc}", session, preview_rows)
        _append_session_history(
            session,
            action="load_snapshot",
            summary=f"加载快照 {loaded_name}",
            details={"snapshot": loaded_name, "undo_count": len(session.undo_stack)},
        )
        trace.append(f"已加载快照：{loaded_name}")
        return (f"已加载快照：{loaded_name}。", session, preview_rows)

    if action == "list_snapshots":
        names = list(session.snapshots.keys())
        if not names:
            return ("当前没有已保存快照。", session, preview_rows)
        _append_session_history(
            session,
            action="list_snapshots",
            summary="查看快照列表",
            details={"total_snapshots": len(names)},
        )
        preview_names = ", ".join(names[-10:])
        trace.append(f"快照列表：{preview_names}")
        return (f"已保存快照（最近 {min(len(names), 10)} 个）：{preview_names}。", session, preview_rows)

    if action == "preview":
        preview_rows = max(1, min(int(command.get("rows", PREVIEW_ROWS)), 200))
        active = _active_df(session)
        _append_session_history(
            session,
            action="preview",
            summary=f"刷新预览前 {preview_rows} 行",
            details={"rows": preview_rows, "current_rows": int(len(active))},
        )
        trace.append(f"刷新预览：前 {preview_rows} 行")
        return (
            f"已刷新预览，当前显示前 {preview_rows} 行（数据总行数 {len(active)}）。",
            session,
            preview_rows,
        )

    if action == "reset_view":
        _push_undo_snapshot(session)
        session.view_df = session.df.copy()
        _append_session_history(
            session,
            action="reset_view",
            summary="重置到原始数据视图",
            details={"rows": int(len(session.df))},
        )
        trace.append("已重置为原始数据视图")
        return ("已重置筛选/排序，恢复到原始数据视图。", session, preview_rows)

    if action == "clear_data":
        if session is not None:
            _append_session_history(session, action="clear_data", summary="清空当前会话数据")
        SESSIONS.pop(session_id, None)
        trace.append("已清空会话中的数据")
        return ("已清空当前会话数据。可继续聊天，或发送“加载文件 路径”重新载入。", None, preview_rows)

    active = _active_df(session)
    columns = [str(c) for c in active.columns]

    if action == "clip_group_range":
        group_column, group_col_err = _resolve_column_with_error(
            str(command.get("group_column", "")),
            columns=columns,
            field_name="group_column",
            trace=trace,
            err_prefix="范围修改失败",
        )
        if group_col_err:
            return (group_col_err, session, preview_rows)
        target_column, target_col_err = _resolve_column_with_error(
            str(command.get("target_column", "")),
            columns=columns,
            field_name="target_column",
            trace=trace,
            err_prefix="范围修改失败",
        )
        if target_col_err:
            return (target_col_err, session, preview_rows)
        if not group_column or not target_column:
            return ("范围修改失败：列信息无效。", session, preview_rows)

        lower = float(command.get("lower", 0))
        upper = float(command.get("upper", 0))
        if lower > upper:
            lower, upper = upper, lower

        source_df = session.df
        group_value = command.get("group_value")
        mask = source_df[group_column] == group_value
        matched_count = int(mask.sum())
        if matched_count <= 0:
            return (f"范围修改完成：{group_column} == {group_value} 未匹配到任何行。", session, preview_rows)

        numeric_series = pd.to_numeric(source_df[target_column], errors="coerce")
        numeric_mask = mask & numeric_series.notna()
        updatable_count = int(numeric_mask.sum())
        if updatable_count <= 0:
            return (
                f"范围修改失败：匹配到 {matched_count} 行，但列 {target_column} 没有可处理的数值。",
                session,
                preview_rows,
            )

        _push_undo_snapshot(session)
        clipped = numeric_series.clip(lower=lower, upper=upper)
        update_indices = source_df.index[numeric_mask]
        source_df.loc[update_indices, target_column] = clipped.loc[update_indices]
        if session.view_df is not None:
            view_indices = session.view_df.index.intersection(update_indices)
            if len(view_indices) > 0:
                session.view_df.loc[view_indices, target_column] = source_df.loc[view_indices, target_column]

        skipped_non_numeric = matched_count - updatable_count
        _append_session_history(
            session,
            action="clip_group_range",
            summary=f"按组裁剪列 {target_column} 到 [{lower:g}, {upper:g}]",
            details={
                "group_column": group_column,
                "group_value": group_value,
                "updated_rows": updatable_count,
                "skipped_non_numeric": skipped_non_numeric,
            },
        )
        trace.append(
            f"范围裁剪完成：{group_column}=={group_value}, col={target_column}, range=[{lower}, {upper}], updated={updatable_count}, skipped_non_numeric={skipped_non_numeric}"
        )
        summary = (
            f"已将 {group_column} 为 {group_value} 的 {updatable_count} 行 {target_column} 限制到 [{lower:g}, {upper:g}]。"
        )
        if skipped_non_numeric > 0:
            summary += f" 另有 {skipped_non_numeric} 行因非数值未修改。"
        return (summary, session, preview_rows)

    if action == "update_cell_range":
        row_start = int(command.get("row_start", 0))
        row_end = int(command.get("row_end", 0))
        if row_start < 1 or row_end < 1:
            return ("单元格批量修改失败：行号必须从 1 开始。", session, preview_rows)
        if row_start > row_end:
            row_start, row_end = row_end, row_start
        if row_end > len(active):
            return (f"单元格批量修改失败：第 {row_end} 行超出当前视图范围（共 {len(active)} 行）。", session, preview_rows)
        update_count = row_end - row_start + 1
        if update_count > MAX_CELL_RANGE_UPDATES:
            return (
                f"单元格批量修改失败：一次最多允许更新 {MAX_CELL_RANGE_UPDATES} 个单元格，当前请求 {update_count} 个。",
                session,
                preview_rows,
            )

        resolved, column_number, err = _resolve_update_column(command, columns, trace)
        if err:
            return (err, session, preview_rows)
        if not resolved or column_number is None:
            return ("单元格批量修改失败：列信息无效。", session, preview_rows)

        raw_value = command.get("value")
        try:
            new_value = _coerce_cell_value_for_series(raw_value, session.df[resolved])
        except Exception:
            return (f"单元格批量修改失败：列 {resolved} 需要与原类型兼容的值。", session, preview_rows)

        source_indices = list(active.index[row_start - 1 : row_end])
        if not source_indices:
            return ("单元格批量修改失败：没有可更新的行。", session, preview_rows)

        _push_undo_snapshot(session)
        session.df.loc[source_indices, resolved] = new_value
        if session.view_df is not None:
            session.view_df.loc[source_indices, resolved] = new_value
        _append_session_history(
            session,
            action="update_cell_range",
            summary=f"批量更新第 {row_start}-{row_end} 行第 {column_number} 列",
            details={"column": resolved, "count": len(source_indices), "value": new_value},
        )

        trace.append(
            f"已批量更新单元格：rows={row_start}-{row_end}, col={column_number}({resolved}), new={new_value}, count={len(source_indices)}"
        )
        return (
            f"已将第 {row_start} 到 {row_end} 行第 {column_number} 列（{resolved}）更新为 {new_value}，共 {len(source_indices)} 个单元格。",
            session,
            preview_rows,
        )

    if action == "update_cell":
        row_number = int(command.get("row", 0))
        if row_number < 1:
            return ("单元格修改失败：行号必须从 1 开始。", session, preview_rows)
        row_index = row_number - 1
        if row_index >= len(active):
            return (f"单元格修改失败：第 {row_number} 行超出当前视图范围（共 {len(active)} 行）。", session, preview_rows)

        resolved, column_number, err = _resolve_update_column(command, columns, trace)
        if err:
            return (err, session, preview_rows)
        if not resolved or column_number is None:
            return ("单元格修改失败：列信息无效。", session, preview_rows)

        source_index = active.index[row_index]
        raw_value = command.get("value")
        try:
            new_value = _coerce_cell_value_for_series(raw_value, session.df[resolved])
        except Exception:
            return (f"单元格修改失败：列 {resolved} 需要与原类型兼容的值。", session, preview_rows)

        old_value = session.df.at[source_index, resolved] if source_index in session.df.index else None
        _push_undo_snapshot(session)
        session.df.at[source_index, resolved] = new_value
        if session.view_df is not None and source_index in session.view_df.index:
            session.view_df.at[source_index, resolved] = new_value
        _append_session_history(
            session,
            action="update_cell",
            summary=f"更新第 {row_number} 行第 {column_number} 列",
            details={"column": resolved, "old": old_value, "new": new_value},
        )

        trace.append(
            f"已更新单元格：row={row_number}, col={column_number}({resolved}), old={old_value}, new={new_value}"
        )
        return (
            f"已将第 {row_number} 行第 {column_number} 列（{resolved}）从 {old_value} 改为 {new_value}。",
            session,
            preview_rows,
        )

    if action == "sort":
        requested = str(command.get("column", "")).strip()
        ascending = bool(command.get("ascending", True))
        try:
            resolved = resolve_column_name(requested, columns, field_name="sort", notes=trace)
        except ValueError:
            return (f"未找到排序列：{requested}。请使用现有列名。", session, preview_rows)
        if not resolved:
            return ("排序指令缺少列名。", session, preview_rows)

        _push_undo_snapshot(session)
        session.view_df = active.sort_values(by=resolved, ascending=ascending, kind="stable")
        _append_session_history(
            session,
            action="sort",
            summary=f"按列 {resolved} {'升序' if ascending else '降序'} 排序",
            details={"column": resolved, "ascending": ascending, "rows": int(len(session.view_df))},
        )
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

        _push_undo_snapshot(session)
        session.view_df = filtered
        _append_session_history(
            session,
            action="filter",
            summary=f"筛选 {resolved} {op} {value}",
            details={"column": resolved, "op": op, "value": value, "rows": int(len(filtered))},
        )
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
    _append_session_history(
        session,
        action="upload_file",
        summary=f"上传文件 {session.filename}",
        details={"rows": int(len(df)), "columns": int(len(df.columns))},
    )
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
    explicit = re.search(
        r"(?:chart_type|chart|type|图类型)\s*(?:=|:)\s*(scatter|line|bar|hist|box|violin|heatmap|composed)",
        lower,
        flags=re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1).lower()

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


def _extract_key_value_token(message: str, keys: list[str]) -> str | None:
    safe_keys = "|".join(re.escape(key) for key in keys)
    pattern = rf"(?:^|[\s,，;；])(?:{safe_keys})\s*(?:=|:)\s*([A-Za-z0-9_\u4e00-\u9fff\-\(\)（）]{{1,60}})"
    match = re.search(pattern, message, flags=re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).strip()
    return token or None


def _extract_stats_toggle(message: str) -> bool | None:
    explicit = re.search(
        r"(?:stats|stats_overlay|统计)\s*(?:=|:)\s*(on|off|true|false|1|0|yes|no)",
        message,
        flags=re.IGNORECASE,
    )
    if explicit:
        value = explicit.group(1).lower()
        return value in {"on", "true", "1", "yes"}

    if re.search(r"(统计标注|显著性|p值|p 值|效应量|effect size)", message, flags=re.IGNORECASE):
        return True
    if re.search(r"(关闭统计|不要统计标注|取消统计标注)", message, flags=re.IGNORECASE):
        return False
    return None


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
    if re.search(
        r"(x轴|y轴|横轴|纵轴|hue|调色板|palette|颜色|标题|title|agg|聚合|bins|分箱|facet|分面|双轴|回归|统计标注|stats|chart_type|type|x=|y=)",
        message,
        flags=re.IGNORECASE,
    ):
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
        group_hint = _extract_key_value_token(message, ["hue", "group", "group_by", "groupby", "分组列", "颜色列"])
        if not group_hint:
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

    x_hint = _extract_key_value_token(message, ["x", "x轴", "横轴"])
    if not x_hint:
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

    y_hint = _extract_key_value_token(message, ["y", "y轴", "纵轴"])
    if not y_hint:
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
        facet_hint = _extract_key_value_token(message, ["facet", "分面列"])
        if not facet_hint:
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

    stats_toggle = _extract_stats_toggle(message)
    if stats_toggle is True:
        out["stats_overlay"] = {"enabled": True, "method": "auto"}
        trace.append("按请求启用统计标注图层")
    elif stats_toggle is False:
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


def _safe_csv_name(raw_name: str | None) -> str:
    base = (raw_name or "table").strip()
    if not base:
        base = "table"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base[:80].strip("._-")
    if not base:
        base = "table"
    if not base.lower().endswith(".csv"):
        base = f"{base}.csv"
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
    mode = request.mode
    trace: list[str] = [f"收到用户请求，开始解析，mode={mode}"]
    session_id = request.session_id or uuid.uuid4().hex
    session = SESSIONS.get(session_id)

    if mode == "chat":
        trace.append("chat 模式：仅返回对话，不执行表格或绘图动作")
        summary, used_fallback = _general_chat_reply(request.message, has_dataset=bool(session))
        table_payload: dict[str, Any] | None = None
        plot_spec_payload: dict[str, Any] | None = None
        plot_payload: dict[str, Any] | None = None
        stats: dict[str, Any] | None = None
        warnings: list[str] = []
        if session:
            table_payload = _table_state(session)
            plot_spec_payload, plot_payload, stats, warnings = _current_plot_context(session, trace)
        return {
            "session_id": session_id,
            "summary": summary,
            "used_fallback": used_fallback,
            "plot_spec": plot_spec_payload,
            "stats": stats,
            "warnings": warnings,
            "thinking": _limit_trace(trace),
            "table_state": table_payload,
            "plot_payload": plot_payload,
            "legacy_image_base64": "",
            "raw_model_text": "",
            "mode_used": "chat",
            "intent": "chat",
        }

    table_command = _table_command_from_message(request.message)
    if mode == "table" and not table_command:
        trace.append("table 模式下未识别表格指令")
        table_payload: dict[str, Any] | None = _table_state(session) if session else None
        plot_spec_payload: dict[str, Any] | None = None
        plot_payload: dict[str, Any] | None = None
        stats: dict[str, Any] | None = None
        warnings: list[str] = []
        if session:
            plot_spec_payload, plot_payload, stats, warnings = _current_plot_context(session, trace)
        return {
            "session_id": session_id,
            "summary": "当前为 table 模式，仅执行表格指令。可输入：筛选 group == A、按 value 降序、把第一行第二列的值改成2。",
            "used_fallback": False,
            "plot_spec": plot_spec_payload,
            "stats": stats,
            "warnings": warnings,
            "thinking": _limit_trace(trace),
            "table_state": table_payload,
            "plot_payload": plot_payload,
            "legacy_image_base64": "",
            "raw_model_text": "",
            "mode_used": "table",
            "intent": "table",
        }

    if table_command and mode in {"auto", "table"}:
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
            "mode_used": mode,
            "intent": "table",
        }

    session = SESSIONS.get(session_id)
    if not session:
        if mode == "plot":
            trace.append("plot 模式下未检测到可用数据")
            return {
                "session_id": session_id,
                "summary": "当前为 plot 模式，但还没有可用数据。请先加载文件，例如：加载文件 /home/zhang/xxx.csv。",
                "used_fallback": False,
                "plot_spec": None,
                "stats": None,
                "warnings": [],
                "thinking": _limit_trace(trace),
                "table_state": None,
                "plot_payload": None,
                "legacy_image_base64": "",
                "raw_model_text": "",
                "mode_used": "plot",
                "intent": "plot",
            }
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
            "mode_used": "auto",
            "intent": "chat",
        }

    df = _active_df(session)
    columns = [str(c) for c in df.columns]
    trace.append(
        f"已载入数据：{session.filename}，当前视图 {len(df)} 行 / 原始 {len(session.df)} 行，{len(columns)} 列"
    )

    has_existing_spec = session.last_plot_spec is not None
    if mode == "auto" and not _has_plot_intent(request.message, has_existing_spec=has_existing_spec):
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
            "mode_used": "auto",
            "intent": "chat",
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
    used_cached_spec = False
    model_raw_text = ""

    cache_key = _normalize_plot_message_key(request.message)
    cached = session.plot_message_cache.get(cache_key)
    if cached:
        spec_data = json.loads(json.dumps(cached))
        used_cached_spec = True
        trace.append("命中会话绘图缓存，复用上次同请求 PlotSpec")
    elif template_spec:
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

    if not used_rule_engine and not used_cached_spec:
        spec_data = _apply_request_overrides(request.message, spec_data, columns, trace)
    spec = _validate_spec_or_400(spec_data, columns, trace)
    session.last_plot_spec = spec
    spec_payload = _spec_to_dict(spec)
    if cache_key:
        session.plot_message_cache[cache_key] = spec_payload
        session.plot_message_cache = _trim_plot_cache(session.plot_message_cache)
    current_fingerprint = _spec_fingerprint(spec_payload)
    unchanged = current_fingerprint == session.last_plot_fingerprint
    session.last_plot_fingerprint = current_fingerprint

    _append_session_history(
        session,
        action="plot_reuse" if used_cached_spec else "plot",
        summary=f"生成图表 {spec.chart_type}" if not used_cached_spec else f"复用图表 {spec.chart_type}",
        details={
            "mode": mode,
            "used_fallback": used_fallback,
            "chart_type": spec.chart_type,
            "cache_hit": used_cached_spec,
            "unchanged": unchanged,
        },
    )
    trace.append(
        f"规范校验通过：chart={spec.chart_type}, x={spec.x}, y={spec.y}, hue={spec.hue}, palette={spec.palette}"
    )

    if used_cached_spec:
        response_summary = f"已复用上次同请求图表（{spec.chart_type}，稳定输出）。"
    elif explicit_edit:
        response_summary = f"已按指令更新当前图表参数（{spec.chart_type}）。"
    elif unchanged:
        response_summary = f"图表参数未变化，已按当前数据刷新 {spec.chart_type} 图。"
    elif used_fallback:
        response_summary = f"模型暂不可用，已通过规则引擎生成 {spec.chart_type} 图。"
    else:
        response_summary = f"已按请求生成 {spec.chart_type} 图。"

    response = _build_chart_response(
        session_id=session_id,
        session=session,
        spec=spec,
        summary=response_summary,
        trace=trace,
        used_fallback=used_fallback,
        model_raw_text=model_raw_text,
        include_legacy_render=cfg.model.enable_legacy_backend_render,
    )
    response["mode_used"] = mode
    response["intent"] = "plot"
    return response


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
    _append_session_history(
        session,
        action="preview_spec",
        summary=f"应用手动 PlotSpec（{spec.chart_type}）",
        details={"chart_type": spec.chart_type},
    )
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


@app.get("/api/session/state")
def get_session_state(session_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    return {
        "session_id": session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "history_count": int(len(session.history)),
        "has_plot_spec": session.last_plot_spec is not None,
        "undo_count": int(len(session.undo_stack)),
        "redo_count": int(len(session.redo_stack)),
        "snapshots": list(session.snapshots.keys()),
        "table_state": _table_state(session),
    }


@app.get("/api/session/history")
def get_session_history(session_id: str, limit: int = 50) -> dict[str, Any]:
    if limit < 1 or limit > MAX_SESSION_HISTORY:
        raise HTTPException(status_code=400, detail=f"limit must be in [1, {MAX_SESSION_HISTORY}]")

    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    items = session.history[-limit:]
    return {
        "session_id": session_id,
        "total": int(len(session.history)),
        "items": items,
    }


@app.post("/api/export/csv")
def export_csv(request: ExportCsvRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    source_df = _active_df(session) if request.source == "active" else session.df
    csv_text = source_df.to_csv(index=False)
    csv_bytes = csv_text.encode("utf-8")
    download_name = _safe_csv_name(request.filename or f"{Path(session.filename).stem}_{request.source}")
    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "X-Export-Source": request.source,
    }
    _append_session_history(
        session,
        action="export_csv",
        summary=f"导出 CSV（{request.source}）",
        details={"rows": int(len(source_df)), "filename": download_name},
    )
    return Response(content=csv_bytes, media_type="text/csv", headers=headers)


@app.post("/api/export/pdf")
def export_pdf(request: ExportPdfRequest):
    session = SESSIONS.get(request.session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Session not found")

    active = _active_df(session)
    columns = [str(c) for c in active.columns]
    trace: list[str] = []
    spec = _validate_spec_or_400(request.plot_spec, columns, trace)
    render_spec = spec
    used_fallback = False

    try:
        _, pdf_b64, _ = render_plot(active, render_spec)
        pdf_bytes = base64.b64decode(pdf_b64.encode("ascii"))
    except Exception as exc:
        trace.append(f"PDF 主渲染失败，准备降级：{exc}")
        try:
            render_spec = _fallback_renderable_spec(spec, columns, trace)
            _, pdf_b64, _ = render_plot(active, render_spec)
            pdf_bytes = base64.b64decode(pdf_b64.encode("ascii"))
            used_fallback = True
        except Exception as degrade_exc:
            raise HTTPException(status_code=400, detail=f"PDF export failed: {degrade_exc}") from degrade_exc

    download_name = _safe_pdf_name(request.filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "X-Export-Used-Fallback": "true" if used_fallback else "false",
        "X-Export-Chart-Type": render_spec.chart_type,
    }
    _append_session_history(
        session,
        action="export_pdf",
        summary=f"导出 PDF（{render_spec.chart_type}）",
        details={"used_fallback": used_fallback, "filename": download_name},
    )
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
