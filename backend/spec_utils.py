from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Any

import pandas as pd

ALLOWED_CHART_TYPES = {
    "scatter",
    "line",
    "bar",
    "hist",
    "box",
    "violin",
    "heatmap",
    "composed",
}

ALLOWED_MARKS = {
    "scatter",
    "line",
    "bar",
    "hist",
    "boxplot",
    "violin",
    "regression",
}

MARK_ALIASES = {
    "box": "boxplot",
}

LEGACY_CHART_TO_MARK = {
    "scatter": "scatter",
    "line": "line",
    "bar": "bar",
    "hist": "hist",
    "box": "boxplot",
    "violin": "violin",
}

ALLOWED_OPS = {"==", "!=", ">", ">=", "<", "<=", "in"}


@dataclass
class FilterRule:
    column: str
    op: str
    value: Any


@dataclass
class LayerSpec:
    mark: str
    encoding: dict[str, str | None] = field(default_factory=dict)
    jitter: bool = False
    alpha: float | None = None
    box_width: float | None = None
    y_axis: str = "left"
    ci: bool = False
    fit: str | None = None
    name: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class FacetSpec:
    field: str
    columns: int = 3


@dataclass
class StatsOverlaySpec:
    enabled: bool = False
    method: str = "auto"


@dataclass
class PlotSpec:
    chart_type: str
    x: str | None = None
    y: str | None = None
    hue: str | None = None
    palette: str | None = None
    title: str | None = None
    agg: str | None = None
    filters: list[FilterRule] = field(default_factory=list)
    bins: int | None = None
    data_ref: str | None = "active_dataset"
    encoding: dict[str, str | None] = field(default_factory=dict)
    layers: list[LayerSpec] = field(default_factory=list)
    facet: FacetSpec | None = None
    stats_overlay: StatsOverlaySpec = field(default_factory=StatsOverlaySpec)
    style: dict[str, Any] = field(default_factory=dict)


def parse_json_from_model_output(raw_text: str) -> dict[str, Any]:
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Model output is empty")

    code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if code_block_match:
        return json.loads(code_block_match.group(1))

    first = raw_text.find("{")
    last = raw_text.rfind("}")
    if first == -1 or last == -1 or first >= last:
        raise ValueError("No JSON object found in model output")

    return json.loads(raw_text[first : last + 1])


def _normalize_token(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", value).lower()


def resolve_column_name(
    name: str | None,
    columns: list[str],
    *,
    field_name: str = "field",
    notes: list[str] | None = None,
) -> str | None:
    if name is None:
        return None

    target = str(name).strip()
    if not target:
        return None

    if target in columns:
        return target

    lower_map = {c.lower(): c for c in columns}
    lowered = target.lower()
    if lowered in lower_map:
        resolved = lower_map[lowered]
        if notes is not None and resolved != target:
            notes.append(f"{field_name} 列名自动修正：{target} -> {resolved}")
        return resolved

    normalized_map = {_normalize_token(c): c for c in columns}
    normalized = _normalize_token(target)
    if normalized in normalized_map:
        resolved = normalized_map[normalized]
        if notes is not None and resolved != target:
            notes.append(f"{field_name} 列名自动修正：{target} -> {resolved}")
        return resolved

    candidates = get_close_matches(normalized, list(normalized_map.keys()), n=1, cutoff=0.74)
    if candidates:
        resolved = normalized_map[candidates[0]]
        if notes is not None:
            notes.append(f"{field_name} 列名近似匹配：{target} -> {resolved}")
        return resolved

    raise ValueError(f"Unknown column in {field_name}: {target}")


def _coerce_float(
    value: Any,
    *,
    min_value: float,
    max_value: float,
    allow_none: bool,
    label: str,
) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{label} is required")
    num = float(value)
    if num < min_value or num > max_value:
        raise ValueError(f"{label} must be in [{min_value}, {max_value}]")
    return num


def _parse_filters(data: dict[str, Any], columns: list[str]) -> list[FilterRule]:
    filters_raw = data.get("filters", [])
    if not isinstance(filters_raw, list):
        raise ValueError("filters must be a list")

    filters: list[FilterRule] = []
    for idx, item in enumerate(filters_raw[:8]):
        if not isinstance(item, dict):
            raise ValueError("Each filter must be an object")

        column = resolve_column_name(item.get("column"), columns, field_name=f"filters[{idx}].column")
        if not column:
            raise ValueError(f"Unknown filter column: {item.get('column')}")

        op = item.get("op")
        if op not in ALLOWED_OPS:
            raise ValueError(f"Unsupported filter op: {op}")

        filters.append(FilterRule(column=column, op=op, value=item.get("value")))

    return filters


def _resolve_base_encoding(
    data: dict[str, Any],
    columns: list[str],
    *,
    notes: list[str] | None,
) -> tuple[str | None, str | None, str | None, dict[str, str | None]]:
    raw_encoding = data.get("encoding")
    if raw_encoding is None:
        raw_encoding = {}
    if not isinstance(raw_encoding, dict):
        raise ValueError("encoding must be an object")

    hue_raw = data.get("hue") or raw_encoding.get("hue") or raw_encoding.get("color")
    for alias_key in ("group_by", "groupby", "hue_by", "color_by", "group"):
        if hue_raw is None and data.get(alias_key):
            hue_raw = data.get(alias_key)
            if notes is not None:
                notes.append(f"使用别名字段 {alias_key} 作为 hue")
            break

    x = resolve_column_name(data.get("x") or raw_encoding.get("x"), columns, field_name="x", notes=notes)
    y = resolve_column_name(data.get("y") or raw_encoding.get("y"), columns, field_name="y", notes=notes)
    hue = resolve_column_name(hue_raw, columns, field_name="hue", notes=notes)

    return x, y, hue, {"x": x, "y": y, "color": hue, "hue": hue}


def _parse_layers(
    data: dict[str, Any],
    *,
    chart_type: str,
    base_x: str | None,
    base_y: str | None,
    base_hue: str | None,
    columns: list[str],
    notes: list[str] | None,
) -> list[LayerSpec]:
    layers: list[LayerSpec] = []
    raw_layers = data.get("layers")

    if isinstance(raw_layers, list) and raw_layers:
        for idx, item in enumerate(raw_layers[:8]):
            if not isinstance(item, dict):
                raise ValueError("Each layer must be an object")

            mark_raw = str(item.get("mark", "")).strip().lower()
            mark = MARK_ALIASES.get(mark_raw, mark_raw)
            if mark not in ALLOWED_MARKS:
                raise ValueError(f"Unsupported layer mark: {mark_raw}")

            encoding_raw = item.get("encoding")
            if encoding_raw is None:
                encoding_raw = {}
            if not isinstance(encoding_raw, dict):
                raise ValueError(f"layers[{idx}].encoding must be an object")

            layer_x = resolve_column_name(
                encoding_raw.get("x") if "x" in encoding_raw else base_x,
                columns,
                field_name=f"layers[{idx}].x",
                notes=notes,
            )
            layer_y = resolve_column_name(
                encoding_raw.get("y") if "y" in encoding_raw else base_y,
                columns,
                field_name=f"layers[{idx}].y",
                notes=notes,
            )
            hue_raw = encoding_raw.get("hue")
            if hue_raw is None:
                hue_raw = encoding_raw.get("color")
            if hue_raw is None:
                hue_raw = base_hue
            layer_hue = resolve_column_name(hue_raw, columns, field_name=f"layers[{idx}].hue", notes=notes)

            if mark in {"scatter", "line", "boxplot", "violin", "regression"} and (not layer_x or not layer_y):
                raise ValueError(f"layers[{idx}] ({mark}) requires both x and y")
            if mark == "hist" and not layer_x:
                raise ValueError(f"layers[{idx}] (hist) requires x")
            if mark == "bar" and not layer_x:
                raise ValueError(f"layers[{idx}] (bar) requires x")

            alpha = _coerce_float(
                item.get("alpha"),
                min_value=0.0,
                max_value=1.0,
                allow_none=True,
                label=f"layers[{idx}].alpha",
            )
            box_width = _coerce_float(
                item.get("box_width"),
                min_value=0.05,
                max_value=1.0,
                allow_none=True,
                label=f"layers[{idx}].box_width",
            )

            y_axis = str(item.get("y_axis") or item.get("axis") or "left").strip().lower()
            if y_axis not in {"left", "right"}:
                raise ValueError(f"layers[{idx}].y_axis must be left/right")

            fit = None
            if item.get("fit") is not None:
                fit = str(item.get("fit")).strip().lower() or None

            known_keys = {
                "mark",
                "encoding",
                "jitter",
                "alpha",
                "box_width",
                "y_axis",
                "axis",
                "ci",
                "fit",
                "name",
            }
            extra_params = {k: v for k, v in item.items() if k not in known_keys}

            layers.append(
                LayerSpec(
                    mark=mark,
                    encoding={"x": layer_x, "y": layer_y, "hue": layer_hue, "color": layer_hue},
                    jitter=bool(item.get("jitter", False)),
                    alpha=alpha,
                    box_width=box_width,
                    y_axis=y_axis,
                    ci=bool(item.get("ci", mark == "regression")),
                    fit=fit,
                    name=str(item.get("name")).strip()[:64] if item.get("name") else None,
                    params=extra_params,
                )
            )
    else:
        if chart_type == "heatmap":
            # Heatmap is rendered by backend correlation logic and does not require layers.
            return []

        if chart_type == "composed":
            raise ValueError("composed chart requires non-empty layers")

        mark = LEGACY_CHART_TO_MARK.get(chart_type)
        if mark is None:
            raise ValueError(f"Unsupported chart type: {chart_type}")

        if mark in {"scatter", "line", "boxplot", "violin"} and (not base_x or not base_y):
            raise ValueError(f"{chart_type} requires both x and y")
        if mark == "hist" and not base_x:
            raise ValueError("hist requires x")
        if mark == "bar" and not base_x:
            raise ValueError("bar requires x")

        layers.append(
            LayerSpec(
                mark=mark,
                encoding={"x": base_x, "y": base_y, "hue": base_hue, "color": base_hue},
                alpha=0.75 if mark in {"scatter", "hist"} else None,
                ci=False,
            )
        )

    return layers


def _parse_facet(data: dict[str, Any], columns: list[str], *, notes: list[str] | None) -> FacetSpec | None:
    raw = data.get("facet")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("facet must be an object")

    field = resolve_column_name(raw.get("field"), columns, field_name="facet.field", notes=notes)
    if not field:
        return None

    columns_count = int(raw.get("columns", 3))
    if columns_count < 1 or columns_count > 6:
        raise ValueError("facet.columns must be in [1, 6]")

    return FacetSpec(field=field, columns=columns_count)


def _parse_stats_overlay(data: dict[str, Any]) -> StatsOverlaySpec:
    raw = data.get("stats_overlay")
    if raw is None:
        return StatsOverlaySpec(enabled=False, method="auto")
    if isinstance(raw, bool):
        return StatsOverlaySpec(enabled=raw, method="auto")
    if not isinstance(raw, dict):
        raise ValueError("stats_overlay must be bool or object")

    method = str(raw.get("method", "auto")).strip() or "auto"
    return StatsOverlaySpec(enabled=bool(raw.get("enabled", True)), method=method)


def validate_plot_spec(
    data: dict[str, Any],
    columns: list[str],
    *,
    notes: list[str] | None = None,
) -> PlotSpec:
    if not isinstance(data, dict):
        raise ValueError("Plot spec must be an object")

    raw_chart_type = str(data.get("chart_type", "")).strip().lower()
    if raw_chart_type == "boxplot":
        raw_chart_type = "box"
    if not raw_chart_type:
        raw_chart_type = "composed" if isinstance(data.get("layers"), list) and data.get("layers") else "scatter"

    if raw_chart_type not in ALLOWED_CHART_TYPES:
        raise ValueError(f"Unsupported chart type: {raw_chart_type}")

    x, y, hue, encoding = _resolve_base_encoding(data, columns, notes=notes)

    palette = data.get("palette")
    if palette is None and isinstance(data.get("style"), dict):
        palette = data["style"].get("palette")
    if palette is not None:
        palette = str(palette).strip() or None

    style = dict(data.get("style") or {})
    if not isinstance(style, dict):
        raise ValueError("style must be an object")

    title = data.get("title")
    if title is None and isinstance(style.get("title"), str):
        title = style.get("title")
    if title is not None:
        title = str(title)[:120]

    agg = data.get("agg")
    if agg is not None:
        agg = str(agg).lower().strip()
        if agg in {"avg", "average"}:
            agg = "mean"
        elif agg not in {"mean", "median", "sum", "count"}:
            if notes is not None:
                notes.append(f"忽略不支持的 agg={agg}，已自动降级为无聚合")
            agg = None

    bins = data.get("bins")
    if bins is not None:
        bins = int(bins)
        if bins < 2 or bins > 200:
            raise ValueError("bins must be in [2, 200]")

    filters = _parse_filters(data, columns)
    facet = _parse_facet(data, columns, notes=notes)
    stats_overlay = _parse_stats_overlay(data)
    layers = _parse_layers(
        data,
        chart_type=raw_chart_type,
        base_x=x,
        base_y=y,
        base_hue=hue,
        columns=columns,
        notes=notes,
    )

    if raw_chart_type != "composed" and len(layers) > 1:
        raw_chart_type = "composed"
        if notes is not None:
            notes.append("检测到多图层配置，已自动切换 chart_type=composed")

    if raw_chart_type == "heatmap" and layers and layers[0].mark != "hist":
        # Heatmap stays backend-generated correlation map.
        layers = []

    if not x and layers:
        x = layers[0].encoding.get("x")
    if not y and layers:
        y = layers[0].encoding.get("y")
    if not hue and layers:
        hue = layers[0].encoding.get("hue")

    has_right_axis = any(layer.y_axis == "right" for layer in layers)
    if has_right_axis:
        units = style.get("units") if isinstance(style.get("units"), dict) else {}
        right_unit = str(units.get("right", "")).strip() if isinstance(units, dict) else ""
        if not right_unit:
            for layer in layers:
                if layer.y_axis == "right":
                    layer.y_axis = "left"
            if notes is not None:
                notes.append("双轴图缺少右轴单位定义（style.units.right），已自动降级为单轴")

    if title is not None and "title" not in style:
        style["title"] = title

    return PlotSpec(
        chart_type=raw_chart_type,
        x=x,
        y=y,
        hue=hue,
        palette=palette,
        title=title,
        agg=agg,
        filters=filters,
        bins=bins,
        data_ref=str(data.get("data_ref") or "active_dataset"),
        encoding=encoding,
        layers=layers,
        facet=facet,
        stats_overlay=stats_overlay,
        style=style,
    )


def apply_filters(df: pd.DataFrame, filters: list[FilterRule]) -> pd.DataFrame:
    out = df
    for rule in filters:
        col = rule.column
        if col not in out.columns:
            raise ValueError(f"Filter column not found: {col}")

        series = out[col]
        value = rule.value
        if pd.api.types.is_numeric_dtype(series):
            if rule.op == "in":
                if not isinstance(value, list):
                    raise ValueError("Filter 'in' requires list value")
                value = pd.to_numeric(pd.Series(value), errors="raise").tolist()
            elif value is not None:
                value = pd.to_numeric(pd.Series([value]), errors="raise").iloc[0]

        if rule.op == "==":
            out = out[out[col] == value]
        elif rule.op == "!=":
            out = out[out[col] != value]
        elif rule.op == ">":
            out = out[out[col] > value]
        elif rule.op == ">=":
            out = out[out[col] >= value]
        elif rule.op == "<":
            out = out[out[col] < value]
        elif rule.op == "<=":
            out = out[out[col] <= value]
        elif rule.op == "in":
            if not isinstance(value, list):
                raise ValueError("Filter 'in' requires list value")
            out = out[out[col].isin(value)]
        else:
            raise ValueError(f"Unsupported op: {rule.op}")

    return out
