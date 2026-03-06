import unittest
from unittest.mock import patch

import pandas as pd

from backend.plot_payload import build_plot_payload
from backend.spec_utils import PlotSpec, StatsOverlaySpec


class PlotPayloadTests(unittest.TestCase):
    def test_build_plot_payload_uses_precomputed_stats_for_overlay(self):
        df = pd.DataFrame(
            {
                "group": ["A", "A", "B", "B"],
                "value": [1.0, 2.0, 3.0, 4.0],
            }
        )
        spec = PlotSpec(
            chart_type="box",
            x="group",
            y="value",
            stats_overlay=StatsOverlaySpec(enabled=True, method="auto"),
        )
        precomputed = {
            "method": "Welch t-test (scipy)",
            "group_column": "group",
            "value_column": "value",
            "n_groups": 2,
            "group_sizes": {"A": 2, "B": 2},
            "statistic": 1.23,
            "p_value": 0.041,
            "significant": True,
            "significance_stars": "*",
            "effect_size": 0.88,
            "effect_metric": "cohen_d",
        }

        with patch("backend.plot_payload.compute_pvalue", side_effect=AssertionError("should not recompute stats")):
            payload, warnings = build_plot_payload(df, spec, precomputed_stats=precomputed)

        self.assertEqual(warnings, [])
        self.assertIsNotNone(payload.get("stats_overlay"))
        self.assertEqual(payload["stats_overlay"]["stats"], precomputed)
        self.assertIn("p=", payload["stats_overlay"]["label"])

    def test_build_plot_payload_skips_stats_when_overlay_disabled(self):
        df = pd.DataFrame(
            {
                "x": [1, 2, 3, 4],
                "y": [2.1, 1.9, 2.8, 3.2],
            }
        )
        spec = PlotSpec(chart_type="scatter", x="x", y="y")

        with patch("backend.plot_payload.compute_pvalue", side_effect=AssertionError("overlay disabled should not call stats")):
            payload, warnings = build_plot_payload(df, spec)

        self.assertEqual(warnings, [])
        self.assertIsNone(payload.get("stats_overlay"))


if __name__ == "__main__":
    unittest.main()
