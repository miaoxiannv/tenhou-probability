import unittest

import numpy as np
import pandas as pd

from backend.spec_utils import PlotSpec
from backend.stats_engine import compute_pvalue


class StatsEngineTests(unittest.TestCase):
    def test_compute_pvalue_two_groups_returns_result(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame(
            {
                "group": ["A"] * 120 + ["B"] * 120,
                "value": np.concatenate(
                    [
                        rng.normal(loc=0.0, scale=1.0, size=120),
                        rng.normal(loc=1.2, scale=1.0, size=120),
                    ]
                ),
            }
        )

        spec = PlotSpec(chart_type="box", x="group", y="value")
        result = compute_pvalue(df, spec)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("method", result)
        self.assertIn("p_value", result)
        self.assertGreaterEqual(float(result["p_value"]), 0.0)
        self.assertLessEqual(float(result["p_value"]), 1.0)
        self.assertIn("group_sizes", result)

    def test_compute_pvalue_returns_none_for_non_numeric_y(self):
        df = pd.DataFrame(
            {
                "group": ["A", "A", "B", "B"],
                "value": ["x", "y", "z", "w"],
            }
        )
        spec = PlotSpec(chart_type="box", x="group", y="value")
        self.assertIsNone(compute_pvalue(df, spec))


if __name__ == "__main__":
    unittest.main()

