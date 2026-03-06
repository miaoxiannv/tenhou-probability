import unittest

from backend.spec_utils import (
    FilterRule,
    PlotSpec,
    apply_filters,
    parse_json_from_model_output,
    validate_plot_spec,
)


class SpecUtilsTests(unittest.TestCase):
    def test_parse_json_from_model_output(self):
        raw = """
        Here is your spec:
        ```json
        {"chart_type":"box", "x":"group", "y":"IL6"}
        ```
        """
        data = parse_json_from_model_output(raw)
        self.assertEqual(data["chart_type"], "box")

    def test_validate_plot_spec_default_values(self):
        columns = ["group", "IL6"]
        spec = validate_plot_spec(
            {
                "chart_type": "box",
                "x": "group",
                "y": "IL6",
            },
            columns,
        )
        self.assertIsInstance(spec, PlotSpec)
        self.assertEqual(spec.chart_type, "box")
        self.assertEqual(spec.filters, [])

    def test_validate_plot_spec_rejects_unknown_column(self):
        columns = ["group", "IL6"]
        with self.assertRaises(ValueError):
            validate_plot_spec(
                {
                    "chart_type": "scatter",
                    "x": "group",
                    "y": "really_unknown_column_name",
                },
                columns,
            )

    def test_validate_plot_spec_fixes_column_case(self):
        columns = ["group", "IL6"]
        notes: list[str] = []
        spec = validate_plot_spec(
            {
                "chart_type": "box",
                "x": "Group",
                "y": "il6",
            },
            columns,
            notes=notes,
        )
        self.assertEqual(spec.x, "group")
        self.assertEqual(spec.y, "IL6")
        self.assertTrue(any("自动修正" in note for note in notes))

    def test_validate_plot_spec_accepts_hue_alias_and_palette(self):
        columns = ["group", "condition", "IL6"]
        spec = validate_plot_spec(
            {
                "chart_type": "violin",
                "x": "group",
                "y": "IL6",
                "group_by": "condition",
                "palette": "Blues",
            },
            columns,
        )
        self.assertEqual(spec.hue, "condition")
        self.assertEqual(spec.palette, "Blues")

    def test_apply_filters_works(self):
        import pandas as pd

        df = pd.DataFrame(
            {
                "group": ["A", "A", "B", "B"],
                "IL6": [1.0, 2.0, 3.0, 4.0],
            }
        )

        rules = [
            FilterRule(column="group", op="==", value="B"),
            FilterRule(column="IL6", op=">", value=3.1),
        ]
        out = apply_filters(df, rules)
        self.assertEqual(len(out), 1)
        self.assertEqual(float(out.iloc[0]["IL6"]), 4.0)

    def test_validate_plot_spec_supports_layers_and_facet(self):
        columns = ["group", "IL6", "batch"]
        spec = validate_plot_spec(
            {
                "chart_type": "composed",
                "encoding": {"x": "group", "y": "IL6", "color": "batch"},
                "layers": [
                    {"mark": "boxplot", "encoding": {"x": "group", "y": "IL6"}},
                    {"mark": "scatter", "encoding": {"x": "group", "y": "IL6", "hue": "batch"}, "jitter": True, "alpha": 0.5},
                ],
                "facet": {"field": "batch", "columns": 2},
                "stats_overlay": {"enabled": True, "method": "auto"},
            },
            columns,
        )
        self.assertEqual(spec.chart_type, "composed")
        self.assertEqual(len(spec.layers), 2)
        self.assertTrue(spec.stats_overlay.enabled)
        self.assertIsNotNone(spec.facet)
        assert spec.facet is not None
        self.assertEqual(spec.facet.field, "batch")


if __name__ == "__main__":
    unittest.main()
