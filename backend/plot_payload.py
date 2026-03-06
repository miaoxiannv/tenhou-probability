from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .spec_utils import LayerSpec, PlotSpec, apply_filters
from .stats_engine import compute_pvalue

MAX_PLOT_ROWS = 6000
MAX_FACETS = 12
PLOT_SAMPLE_SEED = 42
REGRESSION_POINTS = 60


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        if pd.isna(value):
            return None
        return value

    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _safe_records(df: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in df[columns].itertuples(index=False, name=None):
        records.append({col: _json_scalar(row[idx]) for idx, col in enumerate(columns)})
    return records


def _sample_if_needed(df: pd.DataFrame, mark: str) -> tuple[pd.DataFrame, bool]:
    if len(df) <= MAX_PLOT_ROWS:
        return df, False

    if mark in {"scatter", "line", "hist", "regression"}:
        sampled = df.sample(n=MAX_PLOT_ROWS, random_state=PLOT_SAMPLE_SEED).sort_index()
    else:
        sampled = df.head(MAX_PLOT_ROWS)
    return sampled, True


def _default_layers(spec: PlotSpec) -> list[LayerSpec]:
    if spec.layers:
        return spec.layers

    mark_map = {
        "scatter": "scatter",
        "line": "line",
        "bar": "bar",
        "hist": "hist",
        "box": "boxplot",
        "violin": "violin",
    }
    mark = mark_map.get(spec.chart_type)
    if not mark:
        return []

    return [
        LayerSpec(
            mark=mark,
            encoding={"x": spec.x, "y": spec.y, "hue": spec.hue, "color": spec.hue},
            alpha=0.75 if mark in {"scatter", "hist"} else None,
            ci=False,
        )
    ]


def _facet_slices(df: pd.DataFrame, spec: PlotSpec, warnings: list[str]) -> list[tuple[str, pd.DataFrame]]:
    if not spec.facet:
        return [("all", df)]

    facet_col = spec.facet.field
    if facet_col not in df.columns:
        warnings.append(f"facet 字段 {facet_col} 不存在，已降级为单图")
        return [("all", df)]

    unique_values = [v for v in df[facet_col].dropna().unique().tolist()]
    if len(unique_values) > MAX_FACETS:
        warnings.append(f"facet 类别过多（{len(unique_values)}），仅渲染前 {MAX_FACETS} 个")
        unique_values = unique_values[:MAX_FACETS]

    out: list[tuple[str, pd.DataFrame]] = []
    for value in unique_values:
        chunk = df[df[facet_col] == value]
        if chunk.empty:
            continue
        out.append((str(value), chunk))

    if not out:
        return [("all", df)]
    return out


def _regression_lines(df: pd.DataFrame, x_col: str, y_col: str, hue_col: str | None, ci: bool) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []

    if hue_col and hue_col in df.columns:
        groups = list(df.groupby(hue_col, sort=False))
    else:
        groups = [("all", df)]

    for group_name, sub in groups:
        x_vals = pd.to_numeric(sub[x_col], errors="coerce").to_numpy(dtype=float)
        y_vals = pd.to_numeric(sub[y_col], errors="coerce").to_numpy(dtype=float)
        mask = np.isfinite(x_vals) & np.isfinite(y_vals)
        x_vals = x_vals[mask]
        y_vals = y_vals[mask]

        if len(x_vals) < 3:
            continue
        x_min = float(np.min(x_vals))
        x_max = float(np.max(x_vals))
        if x_min == x_max:
            continue

        slope, intercept = np.polyfit(x_vals, y_vals, 1)
        xs = np.linspace(x_min, x_max, REGRESSION_POINTS)
        ys = slope * xs + intercept

        line_payload: dict[str, Any] = {
            "name": str(group_name),
            "x": [float(v) for v in xs.tolist()],
            "y": [float(v) for v in ys.tolist()],
        }

        if ci and len(x_vals) > 2:
            residuals = y_vals - (slope * x_vals + intercept)
            s_err = float(np.sqrt(np.sum(residuals ** 2) / max(len(x_vals) - 2, 1)))
            x_mean = float(np.mean(x_vals))
            sxx = float(np.sum((x_vals - x_mean) ** 2))
            if sxx > 0 and s_err > 0:
                # Use normal approximation as lightweight CI.
                z_val = 1.96
                conf = z_val * s_err * np.sqrt(1.0 / len(x_vals) + ((xs - x_mean) ** 2 / sxx))
                line_payload["ci_upper"] = [float(v) for v in (ys + conf).tolist()]
                line_payload["ci_lower"] = [float(v) for v in (ys - conf).tolist()]

        lines.append(line_payload)

    return lines


def _layer_payload(df: pd.DataFrame, layer: LayerSpec, spec: PlotSpec) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []

    x_col = layer.encoding.get("x")
    y_col = layer.encoding.get("y")
    hue_col = layer.encoding.get("hue")

    if layer.mark == "regression":
        if not x_col or not y_col:
            warnings.append("regression 层缺少 x/y，已跳过")
            return None, warnings
        if x_col not in df.columns or y_col not in df.columns:
            warnings.append(f"regression 层字段不存在（x={x_col}, y={y_col}），已跳过")
            return None, warnings
        lines = _regression_lines(df, x_col, y_col, hue_col if hue_col in df.columns else None, layer.ci)
        if not lines:
            warnings.append("regression 层缺少足够数值点，已跳过")
            return None, warnings
        return (
            {
                "mark": "regression",
                "encoding": {"x": x_col, "y": y_col, "hue": hue_col},
                "lines": lines,
                "ci": layer.ci,
                "alpha": layer.alpha,
                "y_axis": layer.y_axis,
                "name": layer.name,
                "rows": int(len(df)),
                "total_rows": int(len(df)),
                "truncated": False,
            },
            warnings,
        )

    working_df = df
    output_y = y_col

    if layer.mark in {"line", "bar"} and y_col and spec.agg in {"mean", "median", "sum", "count"}:
        keys = [x_col] if x_col else []
        if hue_col:
            keys.append(hue_col)
        if keys and y_col in working_df.columns:
            if spec.agg == "count":
                grouped = working_df.groupby(keys, as_index=False)[y_col].count()
            else:
                grouped = working_df.groupby(keys, as_index=False)[y_col].agg(spec.agg)
            working_df = grouped
    elif layer.mark == "bar" and not y_col and x_col and x_col in working_df.columns:
        if hue_col and hue_col in working_df.columns:
            grouped = working_df.groupby([x_col, hue_col], as_index=False).size().rename(columns={"size": "count"})
        else:
            grouped = working_df[x_col].value_counts(dropna=False).rename_axis(x_col).reset_index(name="count")
        working_df = grouped
        output_y = "count"

    fields: list[str] = []
    if x_col and x_col in working_df.columns:
        fields.append(x_col)
    if output_y and output_y in working_df.columns:
        fields.append(output_y)
    if hue_col and hue_col in working_df.columns and hue_col not in fields:
        fields.append(hue_col)

    if layer.mark in {"scatter", "line", "bar", "boxplot", "violin"} and (not x_col or not output_y):
        warnings.append(f"{layer.mark} 层缺少 x/y，已跳过")
        return None, warnings
    if layer.mark == "hist" and not x_col:
        warnings.append("hist 层缺少 x，已跳过")
        return None, warnings
    if not fields:
        warnings.append(f"{layer.mark} 层无可用字段，已跳过")
        return None, warnings

    sampled_df, truncated = _sample_if_needed(working_df, layer.mark)
    if truncated:
        warnings.append(f"{layer.mark} 层数据点过多，已抽样至 {MAX_PLOT_ROWS}")

    return (
        {
            "mark": layer.mark,
            "encoding": {"x": x_col, "y": output_y, "hue": hue_col},
            "records": _safe_records(sampled_df, fields),
            "alpha": layer.alpha,
            "jitter": layer.jitter,
            "box_width": layer.box_width,
            "y_axis": layer.y_axis,
            "name": layer.name,
            "rows": int(len(sampled_df)),
            "total_rows": int(len(working_df)),
            "truncated": truncated,
        },
        warnings,
    )


def _stats_overlay_payload(
    df: pd.DataFrame,
    spec: PlotSpec,
    *,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not spec.stats_overlay.enabled:
        return None

    if stats is None:
        stats = compute_pvalue(df, spec)
    if not stats:
        return {
            "enabled": True,
            "method": spec.stats_overlay.method,
            "label": "统计条件不足，未生成显著性标注",
            "stats": None,
        }

    p_val = stats.get("p_value")
    stars = stats.get("significance_stars", "ns")
    effect_value = stats.get("effect_size")
    effect_metric = stats.get("effect_metric") or "effect"

    if isinstance(p_val, (int, float)):
        if p_val < 0.0001:
            p_text = "p < 1e-4"
        else:
            p_text = f"p={float(p_val):.4g}"
    else:
        p_text = "p=NA"

    if isinstance(effect_value, (int, float)):
        effect_text = f"{effect_metric}={float(effect_value):.3f}"
    else:
        effect_text = f"{effect_metric}=NA"

    return {
        "enabled": True,
        "method": spec.stats_overlay.method,
        "label": f"{p_text} {stars} · {effect_text}",
        "stats": stats,
    }


def build_plot_payload(
    df: pd.DataFrame,
    spec: PlotSpec,
    *,
    precomputed_stats: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    filtered = apply_filters(df, spec.filters)
    if filtered.empty:
        raise ValueError("No rows left after filtering")

    if spec.chart_type == "heatmap":
        numeric = [c for c in filtered.columns if pd.api.types.is_numeric_dtype(filtered[c])]
        if len(numeric) < 2:
            raise ValueError("Heatmap requires at least 2 numeric columns")
        corr = filtered[numeric].corr(numeric_only=True).fillna(0.0)
        payload = {
            "chart_type": "heatmap",
            "x_labels": list(corr.columns),
            "y_labels": list(corr.index),
            "z": [[float(v) for v in row] for row in corr.values.tolist()],
            "total_rows": int(len(filtered)),
            "rows": int(len(filtered)),
            "truncated": False,
            "encoding": {"x": spec.x, "y": spec.y, "color": spec.hue},
            "facet": None,
            "layers": [],
            "facets": [],
            "stats_overlay": _stats_overlay_payload(filtered, spec, stats=precomputed_stats),
        }
        return payload, warnings

    layers = _default_layers(spec)
    if not layers:
        raise ValueError("No renderable layers found in plot spec")

    facet_chunks = _facet_slices(filtered, spec, warnings)
    facet_payloads: list[dict[str, Any]] = []
    any_truncated = False

    for facet_key, facet_df in facet_chunks:
        layer_payloads: list[dict[str, Any]] = []
        for layer in layers:
            built, layer_warnings = _layer_payload(facet_df, layer, spec)
            warnings.extend(layer_warnings)
            if not built:
                continue
            any_truncated = any_truncated or bool(built.get("truncated"))
            layer_payloads.append(built)

        if layer_payloads:
            facet_payloads.append(
                {
                    "key": facet_key,
                    "rows": int(len(facet_df)),
                    "layers": layer_payloads,
                }
            )

    if not facet_payloads:
        raise ValueError("All layers were skipped; no renderable output")

    single_facet_layers = facet_payloads[0]["layers"] if len(facet_payloads) == 1 else []
    payload = {
        "chart_type": spec.chart_type,
        "x": spec.x,
        "y": spec.y,
        "hue": spec.hue,
        "agg": spec.agg,
        "encoding": {"x": spec.x, "y": spec.y, "color": spec.hue},
        "facet": {"field": spec.facet.field, "columns": spec.facet.columns} if spec.facet else None,
        "layers": single_facet_layers,
        "facets": facet_payloads if spec.facet else [],
        "total_rows": int(len(filtered)),
        "rows": int(len(filtered)),
        "truncated": any_truncated,
        "stats_overlay": _stats_overlay_payload(filtered, spec, stats=precomputed_stats),
    }

    # Backward-compatible field for old frontend fallbacks.
    first_layer_records = []
    if single_facet_layers:
        first_layer_records = single_facet_layers[0].get("records") or []
    payload["records"] = first_layer_records

    return payload, warnings
