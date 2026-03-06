from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .spec_utils import PlotSpec, apply_filters

try:
    from scipy import stats as scipy_stats
except Exception:  # pragma: no cover - optional dependency
    scipy_stats = None


MAX_PVALUE_ROWS = 8000
PERMUTATION_ROUNDS = 1500
RNG_SEED = 42


@dataclass
class PValueResult:
    method: str
    group_column: str
    value_column: str
    n_groups: int
    group_sizes: dict[str, int]
    statistic: float
    p_value: float
    significant: bool
    significance_stars: str
    effect_size: float
    effect_metric: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["statistic"] = float(payload["statistic"])
        payload["p_value"] = float(payload["p_value"])
        payload["effect_size"] = float(payload["effect_size"])
        return payload


def _is_reasonable_group_col(series: pd.Series) -> bool:
    # Grouping column should be categorical-like and not overly fragmented.
    if pd.api.types.is_numeric_dtype(series):
        return series.nunique(dropna=True) <= 20
    return True


def _pick_group_column(df: pd.DataFrame, spec: PlotSpec) -> str | None:
    candidates = [spec.hue, spec.x]
    for col in candidates:
        if col and col in df.columns and _is_reasonable_group_col(df[col]):
            return col
    return None


def _prepare_group_vectors(
    filtered: pd.DataFrame,
    group_col: str,
    value_col: str,
) -> tuple[list[np.ndarray], dict[str, int]]:
    slim = filtered[[group_col, value_col]]
    if len(slim) > MAX_PVALUE_ROWS:
        slim = slim.sample(MAX_PVALUE_ROWS, random_state=RNG_SEED)

    slim = slim.dropna(subset=[group_col, value_col])
    if slim.empty:
        return [], {}

    if not pd.api.types.is_numeric_dtype(slim[value_col]):
        slim = slim.copy()
        slim[value_col] = pd.to_numeric(slim[value_col], errors="coerce")
        slim = slim.dropna(subset=[value_col])
        if slim.empty:
            return [], {}

    grouped = slim.groupby(group_col, sort=False)[value_col]
    vectors: list[np.ndarray] = []
    sizes: dict[str, int] = {}

    for group_name, vals in grouped:
        arr = vals.to_numpy(dtype=float)
        if len(arr) < 2:
            continue
        vectors.append(arr)
        sizes[str(group_name)] = int(len(arr))

    return vectors, sizes


def _welch_stat(a: np.ndarray, b: np.ndarray) -> float:
    va = float(np.var(a, ddof=1))
    vb = float(np.var(b, ddof=1))
    na = len(a)
    nb = len(b)
    denom = np.sqrt((va / na) + (vb / nb))
    if denom == 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / denom)


def _perm_pvalue_two_group(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    obs = abs(_welch_stat(a, b))
    combined = np.concatenate([a, b])
    split = len(a)
    rng = np.random.default_rng(RNG_SEED)
    hits = 0

    for _ in range(PERMUTATION_ROUNDS):
        rng.shuffle(combined)
        stat = abs(_welch_stat(combined[:split], combined[split:]))
        if stat >= obs:
            hits += 1

    p = (hits + 1) / (PERMUTATION_ROUNDS + 1)
    return obs, p


def _anova_f_stat(groups: list[np.ndarray]) -> float:
    k = len(groups)
    n = sum(len(g) for g in groups)
    grand_mean = np.mean(np.concatenate(groups))
    ss_between = sum(len(g) * (np.mean(g) - grand_mean) ** 2 for g in groups)
    ss_within = sum(np.sum((g - np.mean(g)) ** 2) for g in groups)
    if k <= 1 or n <= k or ss_within == 0:
        return 0.0
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n - k)
    return float(ms_between / ms_within) if ms_within > 0 else 0.0


def _cohen_d(a: np.ndarray, b: np.ndarray) -> float:
    na = len(a)
    nb = len(b)
    if na < 2 or nb < 2:
        return 0.0
    va = float(np.var(a, ddof=1))
    vb = float(np.var(b, ddof=1))
    pooled = ((na - 1) * va + (nb - 1) * vb) / max(na + nb - 2, 1)
    if pooled <= 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / np.sqrt(pooled))


def _eta_squared(groups: list[np.ndarray]) -> float:
    all_values = np.concatenate(groups)
    if len(all_values) == 0:
        return 0.0
    grand_mean = float(np.mean(all_values))
    ss_total = float(np.sum((all_values - grand_mean) ** 2))
    if ss_total <= 0:
        return 0.0
    ss_between = float(sum(len(g) * (float(np.mean(g)) - grand_mean) ** 2 for g in groups))
    return float(max(0.0, min(1.0, ss_between / ss_total)))


def _pvalue_stars(p_value: float) -> str:
    if p_value < 0.001:
        return "***"
    if p_value < 0.01:
        return "**"
    if p_value < 0.05:
        return "*"
    return "ns"


def _perm_pvalue_multi_group(groups: list[np.ndarray]) -> tuple[float, float]:
    obs = _anova_f_stat(groups)
    sizes = [len(g) for g in groups]
    combined = np.concatenate(groups).copy()
    rng = np.random.default_rng(RNG_SEED)
    hits = 0

    for _ in range(PERMUTATION_ROUNDS):
        rng.shuffle(combined)
        shuffled: list[np.ndarray] = []
        start = 0
        for size in sizes:
            shuffled.append(combined[start : start + size])
            start += size
        stat = _anova_f_stat(shuffled)
        if stat >= obs:
            hits += 1

    p = (hits + 1) / (PERMUTATION_ROUNDS + 1)
    return obs, p


def compute_pvalue(df: pd.DataFrame, spec: PlotSpec) -> dict[str, Any] | None:
    if not spec.y or spec.y not in df.columns:
        return None
    if not pd.api.types.is_numeric_dtype(df[spec.y]):
        return None

    filtered = apply_filters(df, spec.filters)
    if filtered.empty:
        return None

    group_col = _pick_group_column(filtered, spec)
    if not group_col:
        return None

    vectors, sizes = _prepare_group_vectors(filtered, group_col, spec.y)
    if len(vectors) < 2:
        return None

    if len(vectors) == 2:
        if scipy_stats is not None:
            stat, p = scipy_stats.ttest_ind(vectors[0], vectors[1], equal_var=False, nan_policy="omit")
            method = "Welch t-test (scipy)"
            stat_value = float(abs(stat))
            p_value = float(p)
        else:
            stat_value, p_value = _perm_pvalue_two_group(vectors[0], vectors[1])
            method = "Welch t-test (permutation)"
        effect_size = _cohen_d(vectors[0], vectors[1])
        effect_metric = "cohen_d"
    else:
        if scipy_stats is not None:
            stat, p = scipy_stats.f_oneway(*vectors)
            method = "One-way ANOVA (scipy)"
            stat_value = float(stat)
            p_value = float(p)
        else:
            stat_value, p_value = _perm_pvalue_multi_group(vectors)
            method = "One-way ANOVA (permutation)"
        effect_size = _eta_squared(vectors)
        effect_metric = "eta_squared"

    result = PValueResult(
        method=method,
        group_column=group_col,
        value_column=spec.y,
        n_groups=len(vectors),
        group_sizes=sizes,
        statistic=stat_value,
        p_value=p_value,
        significant=bool(p_value < 0.05),
        significance_stars=_pvalue_stars(p_value),
        effect_size=effect_size,
        effect_metric=effect_metric,
    )
    return result.to_dict()
