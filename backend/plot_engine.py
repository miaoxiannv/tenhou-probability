from __future__ import annotations

import base64
import io
import re

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import scienceplots  # noqa: F401
import seaborn as sns

from .spec_utils import PlotSpec, apply_filters


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def _render_heatmap(df: pd.DataFrame, spec: PlotSpec):
    numeric = _numeric_columns(df)
    if len(numeric) < 2:
        raise ValueError("Heatmap requires at least 2 numeric columns")

    corr = df[numeric].corr(numeric_only=True)
    sns.heatmap(corr, cmap=spec.palette or "viridis", annot=False)


def _has_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in str(text))


def _to_ascii_label(text: str | None, fallback: str) -> str:
    raw = "" if text is None else str(text)
    cleaned = re.sub(r"[^\x20-\x7E]+", "", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:60] if cleaned else fallback


def _rename_non_ascii_column(
    data: pd.DataFrame,
    col_name: str | None,
    fallback_alias: str,
) -> tuple[pd.DataFrame, str | None]:
    if not col_name:
        return data, col_name
    if not _has_non_ascii(col_name):
        return data, col_name

    alias = fallback_alias
    counter = 1
    while alias in data.columns:
        alias = f"{fallback_alias}_{counter}"
        counter += 1
    return data.rename(columns={col_name: alias}), alias


def _encode_non_ascii_categories(
    data: pd.DataFrame,
    col_name: str | None,
    prefix: str,
) -> pd.DataFrame:
    if not col_name or col_name not in data.columns:
        return data
    if pd.api.types.is_numeric_dtype(data[col_name]):
        return data

    series = data[col_name].astype(str)
    if not series.map(_has_non_ascii).any():
        return data

    unique_vals = list(dict.fromkeys(series.tolist()))
    mapping = {val: f"{prefix}{idx + 1}" for idx, val in enumerate(unique_vals)}
    data[col_name] = series.map(mapping)
    return data


def _normalize_palette_name(palette: str | None) -> str | None:
    if palette is None:
        return None

    raw = str(palette).strip()
    if not raw:
        return None

    try:
        sns.color_palette(raw)
        return raw
    except Exception:
        pass

    cmap_map = {name.lower(): name for name in plt.colormaps()}
    lowered = raw.lower()
    if lowered in cmap_map:
        candidate = cmap_map[lowered]
        try:
            sns.color_palette(candidate)
            return candidate
        except Exception:
            pass

    try:
        sns.color_palette(lowered)
        return lowered
    except Exception:
        return None


def render_plot(df: pd.DataFrame, spec: PlotSpec) -> tuple[str, str, str]:
    filtered = apply_filters(df, spec.filters).copy()
    if filtered.empty:
        raise ValueError("No rows left after filtering")

    plot_df = filtered.copy()
    x_col = spec.x
    y_col = spec.y
    hue_col = spec.hue

    plot_df, x_col = _rename_non_ascii_column(plot_df, x_col, "x_axis")
    plot_df, y_col = _rename_non_ascii_column(plot_df, y_col, "y_axis")
    plot_df, hue_col = _rename_non_ascii_column(plot_df, hue_col, "group")
    plot_df = _encode_non_ascii_categories(plot_df, x_col, "X")
    plot_df = _encode_non_ascii_categories(plot_df, hue_col, "G")

    plt.style.use(["science", "no-latex"])
    sns.set_theme(style="ticks", context="talk")

    fig, ax = plt.subplots(figsize=(7.5, 4.8), dpi=160)
    palette = _normalize_palette_name(spec.palette)
    palette_for_hue = palette if hue_col else None

    if spec.chart_type == "scatter":
        sns.scatterplot(data=plot_df, x=x_col, y=y_col, hue=hue_col, palette=palette_for_hue, ax=ax)
    elif spec.chart_type == "line":
        if spec.agg and spec.agg in {"mean", "median", "sum"}:
            group_keys = [x_col] + ([hue_col] if hue_col else [])
            grouped = plot_df.groupby(group_keys, as_index=False)[y_col].agg(spec.agg)
            sns.lineplot(
                data=grouped,
                x=x_col,
                y=y_col,
                hue=hue_col,
                marker="o",
                palette=palette_for_hue,
                ax=ax,
            )
        else:
            sns.lineplot(data=plot_df, x=x_col, y=y_col, hue=hue_col, marker="o", palette=palette_for_hue, ax=ax)
    elif spec.chart_type == "bar":
        if y_col:
            if spec.agg and spec.agg in {"mean", "median", "sum"}:
                group_keys = [x_col] + ([hue_col] if hue_col else [])
                grouped = plot_df.groupby(group_keys, as_index=False)[y_col].agg(spec.agg)
                sns.barplot(data=grouped, x=x_col, y=y_col, hue=hue_col, palette=palette_for_hue, ax=ax)
            else:
                sns.barplot(data=plot_df, x=x_col, y=y_col, hue=hue_col, palette=palette_for_hue, ax=ax)
        else:
            counts = plot_df[x_col].value_counts().reset_index()
            counts.columns = [x_col, "count"]
            sns.barplot(data=counts, x=x_col, y="count", palette=palette, ax=ax)
    elif spec.chart_type == "hist":
        sns.histplot(data=plot_df, x=x_col, hue=hue_col, palette=palette_for_hue, bins=spec.bins or 30, ax=ax)
    elif spec.chart_type == "box":
        sns.boxplot(data=plot_df, x=x_col, y=y_col, hue=hue_col, palette=palette_for_hue, ax=ax)
    elif spec.chart_type == "violin":
        sns.violinplot(data=plot_df, x=x_col, y=y_col, hue=hue_col, palette=palette_for_hue, ax=ax)
    elif spec.chart_type == "heatmap":
        _render_heatmap(plot_df, spec)
    else:
        raise ValueError(f"Unsupported chart type: {spec.chart_type}")

    safe_title = _to_ascii_label(spec.title, f"{spec.chart_type.title()} Plot")
    ax.set_title(safe_title)
    if x_col:
        ax.set_xlabel(_to_ascii_label(x_col, "X"))
    if y_col:
        ax.set_ylabel(_to_ascii_label(y_col, "Y"))

    fig.tight_layout()

    png_buffer = io.BytesIO()
    fig.savefig(png_buffer, format="png", dpi=180, bbox_inches="tight", pad_inches=0.1)

    pdf_buffer = io.BytesIO()
    fig.savefig(pdf_buffer, format="pdf", dpi=300, bbox_inches=None)

    plt.close(fig)
    encoded_png = base64.b64encode(png_buffer.getvalue()).decode("ascii")
    encoded_pdf = base64.b64encode(pdf_buffer.getvalue()).decode("ascii")

    code = _spec_to_python_code(spec)
    return encoded_png, encoded_pdf, code


def _spec_to_python_code(spec: PlotSpec) -> str:
    return (
        "import seaborn as sns\n"
        "import matplotlib.pyplot as plt\n"
        "import scienceplots\n"
        "plt.style.use(['science', 'no-latex'])\n"
        f"# chart_type={spec.chart_type}, x={spec.x}, y={spec.y}, hue={spec.hue}, palette={spec.palette}\n"
        "# Replace `df` with your DataFrame\n"
    )
