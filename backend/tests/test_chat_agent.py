import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi import HTTPException

from backend.main import (
    ChatRequest,
    ExportPdfRequest,
    SESSIONS,
    SpecRequest,
    chat_and_plot,
    compute_stats,
    export_pdf,
    preview_spec,
    static_fallback,
)


class ChatAgentTests(unittest.TestCase):
    def setUp(self):
        self._backup_sessions = dict(SESSIONS)
        self._backup_openai_api_key = os.environ.get("OPENAI_API_KEY")
        self._backup_sub2api_api_key = os.environ.get("SUB2API_API_KEY")
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("SUB2API_API_KEY", None)
        SESSIONS.clear()

    def tearDown(self):
        if self._backup_openai_api_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self._backup_openai_api_key

        if self._backup_sub2api_api_key is None:
            os.environ.pop("SUB2API_API_KEY", None)
        else:
            os.environ["SUB2API_API_KEY"] = self._backup_sub2api_api_key

        SESSIONS.clear()
        SESSIONS.update(self._backup_sessions)

    def _make_csv(self) -> Path:
        fd, raw_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        path = Path(raw_path)
        df = pd.DataFrame(
            {
                "group": ["A", "A", "B", "B"],
                "value": [1.0, 4.0, 3.0, 2.0],
            }
        )
        df.to_csv(path, index=False)
        return path

    def test_chat_can_load_local_file_and_update_table_state(self):
        csv_path = self._make_csv()
        try:
            response = chat_and_plot(
                ChatRequest(session_id="session1234", message=f"加载文件 {csv_path}")
            )
        finally:
            csv_path.unlink(missing_ok=True)

        self.assertEqual(response["session_id"], "session1234")
        self.assertIn("table_state", response)
        self.assertIsNotNone(response["table_state"])
        assert response["table_state"] is not None
        self.assertEqual(response["table_state"]["row_count"], 4)
        self.assertEqual(response["table_state"]["column_count"], 2)
        self.assertEqual(len(response["table_state"]["preview_rows"]), 4)

    def test_chat_filter_sort_reset_and_clear(self):
        csv_path = self._make_csv()
        session_id = "session5678"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        filtered = chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group == A"))
        self.assertIsNotNone(filtered["table_state"])
        assert filtered["table_state"] is not None
        self.assertEqual(filtered["table_state"]["row_count"], 2)
        self.assertEqual(filtered["table_state"]["source_row_count"], 4)

        sorted_view = chat_and_plot(ChatRequest(session_id=session_id, message="按 value 降序"))
        self.assertIsNotNone(sorted_view["table_state"])
        assert sorted_view["table_state"] is not None
        top_value = float(sorted_view["table_state"]["preview_rows"][0]["value"])
        self.assertEqual(top_value, 4.0)

        reset = chat_and_plot(ChatRequest(session_id=session_id, message="重置"))
        self.assertIsNotNone(reset["table_state"])
        assert reset["table_state"] is not None
        self.assertEqual(reset["table_state"]["row_count"], 4)

        cleared = chat_and_plot(ChatRequest(session_id=session_id, message="清空数据"))
        self.assertIsNone(cleared["table_state"])
        self.assertNotIn(session_id, SESSIONS)

    def test_chat_without_dataset_still_replies(self):
        response = chat_and_plot(ChatRequest(session_id="session9012", message="你好"))
        self.assertEqual(response["session_id"], "session9012")
        self.assertIn("summary", response)
        self.assertIsNone(response["plot_spec"])
        self.assertIsNone(response["table_state"])

    def test_preview_spec_and_stats_endpoint(self):
        csv_path = self._make_csv()
        session_id = "session7711"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        spec = {"chart_type": "box", "x": "group", "y": "value"}
        preview = preview_spec(SpecRequest(session_id=session_id, plot_spec=spec))
        self.assertEqual(preview["plot_spec"]["chart_type"], "box")
        self.assertIn("plot_payload", preview)
        self.assertIsNotNone(preview["stats"])

        stats_resp = compute_stats(SpecRequest(session_id=session_id, plot_spec=spec))
        self.assertIn("stats", stats_resp)
        self.assertIsNotNone(stats_resp["stats"])

    def test_chat_edit_after_manual_spec_keeps_existing_axes(self):
        csv_path = self._make_csv()
        session_id = "session3333"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        preview_spec(SpecRequest(session_id=session_id, plot_spec={"chart_type": "box", "x": "group", "y": "value"}))
        response = chat_and_plot(ChatRequest(session_id=session_id, message="把颜色改成蓝色"))

        self.assertFalse(response["used_fallback"])
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertEqual(response["plot_spec"]["chart_type"], "box")
        self.assertEqual(response["plot_spec"]["x"], "group")
        self.assertEqual(response["plot_spec"]["y"], "value")
        self.assertEqual(response["plot_spec"]["palette"], "Blues")
        self.assertNotIn("模型解析失败", response["summary"])

    def test_table_command_refreshes_plot_when_current_spec_exists(self):
        csv_path = self._make_csv()
        session_id = "session4444"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        preview_spec(
            SpecRequest(
                session_id=session_id,
                plot_spec={"chart_type": "scatter", "x": "value", "y": "value", "hue": "group"},
            )
        )
        filtered = chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group == A"))
        self.assertIsNotNone(filtered["plot_spec"])
        self.assertIsNotNone(filtered["plot_payload"])
        assert filtered["plot_payload"] is not None
        self.assertEqual(filtered["table_state"]["row_count"], 2)
        self.assertEqual(filtered["plot_payload"]["rows"], 2)

    def test_chat_can_generate_scatter_box_composed_template(self):
        csv_path = self._make_csv()
        session_id = "session9911"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(ChatRequest(session_id=session_id, message="请画散点+箱线图"))
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertEqual(response["plot_spec"]["chart_type"], "composed")
        marks = [layer.get("mark") for layer in response["plot_spec"].get("layers", [])]
        self.assertIn("boxplot", marks)
        self.assertIn("scatter", marks)
        self.assertIsNotNone(response["plot_payload"])
        assert response["plot_payload"] is not None
        self.assertTrue(len(response["plot_payload"].get("layers", [])) >= 2)

    def test_chat_can_generate_violin_box_jitter_template(self):
        csv_path = self._make_csv()
        session_id = "session9922"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(ChatRequest(session_id=session_id, message="给我一个小提琴+箱线+抖动点组合图"))
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertEqual(response["plot_spec"]["chart_type"], "composed")
        marks = [layer.get("mark") for layer in response["plot_spec"].get("layers", [])]
        self.assertIn("violin", marks)
        self.assertIn("boxplot", marks)
        self.assertIn("scatter", marks)
        scatter_layer = next((layer for layer in response["plot_spec"]["layers"] if layer.get("mark") == "scatter"), None)
        self.assertIsNotNone(scatter_layer)
        assert scatter_layer is not None
        self.assertTrue(bool(scatter_layer.get("jitter")))

    def test_export_pdf_endpoint_returns_pdf_bytes(self):
        csv_path = self._make_csv()
        session_id = "session8822"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = export_pdf(
            ExportPdfRequest(
                session_id=session_id,
                plot_spec={"chart_type": "scatter", "x": "value", "y": "value", "hue": "group"},
                filename="chart_test",
            )
        )
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn('filename="chart_test.pdf"', response.headers.get("Content-Disposition", ""))

    def test_static_fallback_does_not_expose_backend_source(self):
        with self.assertRaises(HTTPException) as ctx:
            static_fallback("backend/main.py")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
