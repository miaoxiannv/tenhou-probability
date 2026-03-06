import unittest

from backend.llm_client import extract_output_text


class LlmClientTests(unittest.TestCase):
    def test_extract_output_text_prefers_top_level(self):
        payload = {"output_text": "{\"chart_type\":\"box\"}"}
        self.assertEqual(extract_output_text(payload), '{"chart_type":"box"}')

    def test_extract_output_text_from_output_items(self):
        payload = {
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": '{"chart_type":"scatter"}'}
                    ]
                }
            ]
        }
        self.assertEqual(extract_output_text(payload), '{"chart_type":"scatter"}')

    def test_extract_output_text_raises_on_missing(self):
        with self.assertRaises(ValueError):
            extract_output_text({"id": "resp_123"})


if __name__ == "__main__":
    unittest.main()
