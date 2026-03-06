import unittest

import pandas as pd

from backend.plot_engine import _to_ascii_label, render_plot
from backend.spec_utils import PlotSpec


class PlotEngineTests(unittest.TestCase):
    def test_render_scatter_plot_returns_png_base64(self):
        df = pd.DataFrame(
            {
                "x": [1, 2, 3, 4],
                "y": [2, 4, 6, 8],
                "group": ["A", "A", "B", "B"],
            }
        )
        spec = PlotSpec(chart_type="scatter", x="x", y="y", hue="group")

        img_b64, pdf_b64, code = render_plot(df, spec)

        self.assertTrue(isinstance(img_b64, str) and len(img_b64) > 200)
        self.assertTrue(isinstance(pdf_b64, str) and len(pdf_b64) > 200)
        self.assertTrue("seaborn" in code)

    def test_to_ascii_label_removes_chinese(self):
        out = _to_ascii_label("按组分箱图", "Box Plot")
        self.assertEqual(out, "Box Plot")

    def test_render_bar_with_agg_and_hue(self):
        df = pd.DataFrame(
            {
                "group": ["A", "A", "B", "B"],
                "subgroup": ["X", "Y", "X", "Y"],
                "value": [1.0, 2.0, 3.0, 4.0],
            }
        )
        spec = PlotSpec(chart_type="bar", x="group", y="value", hue="subgroup", agg="mean")

        img_b64, pdf_b64, _ = render_plot(df, spec)

        self.assertTrue(isinstance(img_b64, str) and len(img_b64) > 200)
        self.assertTrue(isinstance(pdf_b64, str) and len(pdf_b64) > 200)

    def test_render_scatter_accepts_palette_name_with_wrong_case(self):
        df = pd.DataFrame(
            {
                "x": [1, 2, 3, 4],
                "y": [2, 3, 4, 5],
                "group": ["A", "A", "B", "B"],
            }
        )
        spec = PlotSpec(chart_type="scatter", x="x", y="y", hue="group", palette="blues")

        img_b64, pdf_b64, _ = render_plot(df, spec)

        self.assertTrue(isinstance(img_b64, str) and len(img_b64) > 200)
        self.assertTrue(isinstance(pdf_b64, str) and len(pdf_b64) > 200)


if __name__ == "__main__":
    unittest.main()
