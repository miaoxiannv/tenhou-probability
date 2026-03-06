import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from pydantic import ValidationError

from backend.main import (
    ChatRequest,
    ExportCsvRequest,
    ExportPdfRequest,
    SESSIONS,
    SpecRequest,
    chat_and_plot,
    compute_stats,
    export_csv,
    export_pdf,
    get_session_history,
    get_session_state,
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

    def _make_group_expression_csv(self) -> Path:
        fd, raw_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        path = Path(raw_path)
        df = pd.DataFrame(
            {
                "Group": ["Control", "Control", "Treatment", "Control"],
                "Expression": [3.2, 5.8, 9.9, 8.4],
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

    def test_chat_filter_supports_in_and_not_in(self):
        csv_path = self._make_csv()
        session_id = "session6118"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        in_filtered = chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group in [A]"))
        self.assertIsNotNone(in_filtered["table_state"])
        assert in_filtered["table_state"] is not None
        self.assertEqual(in_filtered["table_state"]["row_count"], 2)
        self.assertTrue(all(row["group"] == "A" for row in in_filtered["table_state"]["preview_rows"]))

        chat_and_plot(ChatRequest(session_id=session_id, message="重置"))
        not_in_filtered = chat_and_plot(ChatRequest(session_id=session_id, message="filter group not in [A]"))
        self.assertIsNotNone(not_in_filtered["table_state"])
        assert not_in_filtered["table_state"] is not None
        self.assertEqual(not_in_filtered["table_state"]["row_count"], 2)
        self.assertTrue(all(row["group"] == "B" for row in not_in_filtered["table_state"]["preview_rows"]))

    def test_chat_can_update_cell_by_row_and_column_index(self):
        csv_path = self._make_csv()
        session_id = "session6229"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        updated = chat_and_plot(ChatRequest(session_id=session_id, message="把第一行第二列的值改成2"))
        self.assertIsNotNone(updated["table_state"])
        assert updated["table_state"] is not None
        self.assertEqual(updated["table_state"]["preview_rows"][0]["value"], 2.0)

        reset = chat_and_plot(ChatRequest(session_id=session_id, message="重置"))
        self.assertIsNotNone(reset["table_state"])
        assert reset["table_state"] is not None
        self.assertEqual(reset["table_state"]["preview_rows"][0]["value"], 2.0)

    def test_chat_can_update_cell_on_filtered_view_and_persist(self):
        csv_path = self._make_csv()
        session_id = "session6230"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group == A"))
        chat_and_plot(ChatRequest(session_id=session_id, message="把第二行第二列的值改成9"))
        reset = chat_and_plot(ChatRequest(session_id=session_id, message="重置"))

        self.assertIsNotNone(reset["table_state"])
        assert reset["table_state"] is not None
        self.assertEqual(reset["table_state"]["preview_rows"][1]["value"], 9.0)

    def test_chat_can_update_cell_by_excel_ref(self):
        csv_path = self._make_csv()
        session_id = "session6231"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        updated = chat_and_plot(ChatRequest(session_id=session_id, message="把 B1 改成 8"))
        self.assertIsNotNone(updated["table_state"])
        assert updated["table_state"] is not None
        self.assertEqual(updated["table_state"]["preview_rows"][0]["value"], 8.0)

    def test_chat_can_batch_update_cell_range(self):
        csv_path = self._make_csv()
        session_id = "session6232"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        updated = chat_and_plot(ChatRequest(session_id=session_id, message="把第1到2行第2列的值改成7"))
        self.assertIsNotNone(updated["table_state"])
        assert updated["table_state"] is not None
        self.assertEqual(updated["table_state"]["preview_rows"][0]["value"], 7.0)
        self.assertEqual(updated["table_state"]["preview_rows"][1]["value"], 7.0)

    def test_chat_plot_supports_type_and_axis_equals_syntax(self):
        csv_path = self._make_csv()
        session_id = "session6233"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(
            ChatRequest(session_id=session_id, message="画图 type=line x=group y=value stats=on title=Line Demo")
        )
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertEqual(response["plot_spec"]["chart_type"], "line")
        self.assertEqual(response["plot_spec"]["x"], "group")
        self.assertEqual(response["plot_spec"]["y"], "value")
        self.assertEqual(response["plot_spec"]["title"], "Line Demo")
        self.assertTrue(bool(response["plot_spec"]["stats_overlay"]["enabled"]))

    def test_chat_can_update_sheet_without_upload_by_creating_scratch_table(self):
        session_id = "session6234"
        response = chat_and_plot(ChatRequest(session_id=session_id, message="把第一行第二列的值改成2"))

        self.assertIsNotNone(response["table_state"])
        assert response["table_state"] is not None
        self.assertEqual(response["table_state"]["filename"], "untitled_sheet")
        self.assertGreaterEqual(response["table_state"]["row_count"], 50)
        self.assertGreaterEqual(response["table_state"]["column_count"], 8)
        self.assertEqual(response["table_state"]["preview_rows"][0]["B"], 2)

    def test_chat_can_clip_expression_range_by_group(self):
        csv_path = self._make_group_expression_csv()
        session_id = "session6235"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        updated = chat_and_plot(
            ChatRequest(session_id=session_id, message="把Group中的Control组的所有Expression的范围更改为5-7")
        )
        self.assertIsNotNone(updated["table_state"])
        assert updated["table_state"] is not None
        rows = updated["table_state"]["preview_rows"]
        self.assertEqual(float(rows[0]["Expression"]), 5.0)
        self.assertEqual(float(rows[1]["Expression"]), 5.8)
        self.assertEqual(float(rows[2]["Expression"]), 9.9)
        self.assertEqual(float(rows[3]["Expression"]), 7.0)

    def test_chat_table_mode_executes_table_command(self):
        csv_path = self._make_csv()
        session_id = "session6236"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        filtered = chat_and_plot(
            ChatRequest(session_id=session_id, message="筛选 group == A", mode="table")
        )
        self.assertEqual(filtered["mode_used"], "table")
        self.assertIsNotNone(filtered["table_state"])
        assert filtered["table_state"] is not None
        self.assertEqual(filtered["table_state"]["row_count"], 2)

    def test_chat_table_mode_rejects_non_table_message(self):
        csv_path = self._make_csv()
        session_id = "session6237"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(ChatRequest(session_id=session_id, message="你好", mode="table"))
        self.assertEqual(response["mode_used"], "table")
        self.assertIn("仅执行表格", response["summary"])
        self.assertIsNotNone(response["table_state"])
        assert response["table_state"] is not None
        self.assertEqual(response["table_state"]["row_count"], 4)

    def test_chat_mode_does_not_mutate_table_or_plot(self):
        csv_path = self._make_csv()
        session_id = "session6238"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(
            ChatRequest(session_id=session_id, message="把第一行第二列的值改成2", mode="chat")
        )
        self.assertEqual(response["mode_used"], "chat")
        self.assertIsNotNone(response["table_state"])
        assert response["table_state"] is not None
        self.assertEqual(float(response["table_state"]["preview_rows"][0]["value"]), 1.0)
        self.assertIsNone(response["plot_spec"])

    def test_chat_plot_mode_without_dataset_returns_guidance(self):
        response = chat_and_plot(ChatRequest(session_id="session6239", message="画图", mode="plot"))
        self.assertEqual(response["mode_used"], "plot")
        self.assertIn("先加载文件", response["summary"])
        self.assertIsNone(response["table_state"])
        self.assertIsNone(response["plot_spec"])

    def test_chat_plot_mode_generates_plot(self):
        csv_path = self._make_csv()
        session_id = "session6240"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(ChatRequest(session_id=session_id, message="画一个散点图", mode="plot"))
        self.assertEqual(response["mode_used"], "plot")
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertEqual(response["plot_spec"]["chart_type"], "scatter")

    def test_chat_without_dataset_still_replies(self):
        response = chat_and_plot(ChatRequest(session_id="session9012", message="你好"))
        self.assertEqual(response["session_id"], "session9012")
        self.assertIn("summary", response)
        self.assertIsNone(response["plot_spec"])
        self.assertIsNone(response["table_state"])

    def test_chat_mode_validation_rejects_unknown_mode(self):
        with self.assertRaises(ValidationError):
            ChatRequest(session_id="session9013", message="hello", mode="invalid")

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

    def test_chat_can_generate_heatmap(self):
        csv_path = self._make_csv()
        session_id = "session9923"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = chat_and_plot(ChatRequest(session_id=session_id, message="画热图", mode="plot"))
        self.assertIsNotNone(response["plot_spec"])
        assert response["plot_spec"] is not None
        self.assertIn(response["plot_spec"]["chart_type"], {"heatmap", "scatter"})
        self.assertIsNotNone(response["plot_payload"])

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
        self.assertEqual(response.headers.get("X-Export-Used-Fallback"), "false")

    def test_export_pdf_endpoint_supports_composed_spec_with_fallback(self):
        csv_path = self._make_csv()
        session_id = "session8823"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = export_pdf(
            ExportPdfRequest(
                session_id=session_id,
                plot_spec={
                    "chart_type": "composed",
                    "x": "group",
                    "y": "value",
                    "hue": "group",
                    "layers": [
                        {"mark": "scatter", "encoding": {"x": "group", "y": "value", "hue": "group"}},
                        {"mark": "boxplot", "encoding": {"x": "group", "y": "value"}},
                    ],
                },
                filename="composed_chart",
            )
        )
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn('filename="composed_chart.pdf"', response.headers.get("Content-Disposition", ""))
        self.assertEqual(response.headers.get("X-Export-Used-Fallback"), "true")

    def test_export_pdf_endpoint_supports_heatmap_spec(self):
        csv_path = self._make_csv()
        session_id = "session8824"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        response = export_pdf(
            ExportPdfRequest(
                session_id=session_id,
                plot_spec={"chart_type": "heatmap"},
                filename="heatmap_chart",
            )
        )
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn('filename="heatmap_chart.pdf"', response.headers.get("Content-Disposition", ""))

    def test_session_state_and_history_endpoints(self):
        csv_path = self._make_csv()
        session_id = "session8825"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group == A", mode="table"))
        chat_and_plot(ChatRequest(session_id=session_id, message="按 value 降序", mode="table"))

        state = get_session_state(session_id=session_id)
        self.assertEqual(state["session_id"], session_id)
        self.assertIsNotNone(state["table_state"])
        assert state["table_state"] is not None
        self.assertEqual(state["table_state"]["row_count"], 2)
        self.assertGreaterEqual(int(state["history_count"]), 3)

        history = get_session_history(session_id=session_id, limit=20)
        self.assertEqual(history["session_id"], session_id)
        items = history["items"]
        self.assertGreaterEqual(len(items), 3)
        actions = [item.get("action") for item in items]
        self.assertIn("load_file", actions)
        self.assertIn("filter", actions)

    def test_export_csv_endpoint_returns_active_view_and_original(self):
        csv_path = self._make_csv()
        session_id = "session8826"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        chat_and_plot(ChatRequest(session_id=session_id, message="筛选 group == A", mode="table"))

        active_resp = export_csv(ExportCsvRequest(session_id=session_id, filename="active_view", source="active"))
        self.assertEqual(active_resp.media_type, "text/csv")
        self.assertIn('filename="active_view.csv"', active_resp.headers.get("Content-Disposition", ""))
        active_text = active_resp.body.decode("utf-8")
        self.assertIn("group,value", active_text)
        self.assertEqual(len([ln for ln in active_text.splitlines() if ln.strip()]), 3)

        original_resp = export_csv(ExportCsvRequest(session_id=session_id, filename="original_full", source="original"))
        self.assertEqual(original_resp.media_type, "text/csv")
        self.assertIn('filename="original_full.csv"', original_resp.headers.get("Content-Disposition", ""))
        original_text = original_resp.body.decode("utf-8")
        self.assertEqual(len([ln for ln in original_text.splitlines() if ln.strip()]), 5)

    def test_chat_supports_undo_and_redo(self):
        csv_path = self._make_csv()
        session_id = "session8827"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        changed = chat_and_plot(ChatRequest(session_id=session_id, message="把第一行第二列的值改成8", mode="table"))
        self.assertIsNotNone(changed["table_state"])
        assert changed["table_state"] is not None
        self.assertEqual(float(changed["table_state"]["preview_rows"][0]["value"]), 8.0)

        undone = chat_and_plot(ChatRequest(session_id=session_id, message="撤销", mode="table"))
        self.assertIsNotNone(undone["table_state"])
        assert undone["table_state"] is not None
        self.assertEqual(float(undone["table_state"]["preview_rows"][0]["value"]), 1.0)

        redone = chat_and_plot(ChatRequest(session_id=session_id, message="重做", mode="table"))
        self.assertIsNotNone(redone["table_state"])
        assert redone["table_state"] is not None
        self.assertEqual(float(redone["table_state"]["preview_rows"][0]["value"]), 8.0)

    def test_chat_supports_snapshot_save_list_and_load(self):
        csv_path = self._make_csv()
        session_id = "session8828"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        saved = chat_and_plot(ChatRequest(session_id=session_id, message="保存快照 baseline", mode="table"))
        self.assertIn("baseline", saved["summary"])

        changed = chat_and_plot(ChatRequest(session_id=session_id, message="把第一行第二列的值改成9", mode="table"))
        self.assertIsNotNone(changed["table_state"])
        assert changed["table_state"] is not None
        self.assertEqual(float(changed["table_state"]["preview_rows"][0]["value"]), 9.0)

        loaded = chat_and_plot(ChatRequest(session_id=session_id, message="加载快照 baseline", mode="table"))
        self.assertIsNotNone(loaded["table_state"])
        assert loaded["table_state"] is not None
        self.assertEqual(float(loaded["table_state"]["preview_rows"][0]["value"]), 1.0)

        listed = chat_and_plot(ChatRequest(session_id=session_id, message="查看快照", mode="table"))
        self.assertIn("baseline", listed["summary"])

    def test_plot_repeated_message_reuses_cached_spec(self):
        csv_path = self._make_csv()
        session_id = "session8829"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        first = chat_and_plot(
            ChatRequest(session_id=session_id, message="画图 type=scatter x=group y=value title=Demo", mode="plot")
        )
        second = chat_and_plot(
            ChatRequest(session_id=session_id, message="画图 type=scatter x=group y=value title=Demo", mode="plot")
        )

        self.assertIsNotNone(first["plot_spec"])
        self.assertIsNotNone(second["plot_spec"])
        self.assertEqual(first["plot_spec"], second["plot_spec"])
        self.assertIn("复用", second["summary"])

        history = get_session_history(session_id=session_id, limit=20)
        actions = [item.get("action") for item in history["items"]]
        self.assertIn("plot_reuse", actions)

    def test_session_state_reports_undo_redo_and_snapshots(self):
        csv_path = self._make_csv()
        session_id = "session8830"
        try:
            chat_and_plot(ChatRequest(session_id=session_id, message=f"加载文件 {csv_path}"))
        finally:
            csv_path.unlink(missing_ok=True)

        chat_and_plot(ChatRequest(session_id=session_id, message="保存快照 baseline", mode="table"))
        chat_and_plot(ChatRequest(session_id=session_id, message="把第一行第二列的值改成6", mode="table"))
        state = get_session_state(session_id=session_id)

        self.assertIn("undo_count", state)
        self.assertIn("redo_count", state)
        self.assertIn("snapshots", state)
        self.assertGreaterEqual(int(state["undo_count"]), 1)
        self.assertEqual(int(state["redo_count"]), 0)
        self.assertIn("baseline", state["snapshots"])

    def test_static_fallback_does_not_expose_backend_source(self):
        with self.assertRaises(HTTPException) as ctx:
            static_fallback("backend/main.py")
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
