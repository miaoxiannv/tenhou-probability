from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import ModelConfig


def extract_output_text(payload: dict[str, Any]) -> str:
    top = payload.get("output_text")
    if isinstance(top, str) and top.strip():
        return top

    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    chunks.append(part["text"])

        if chunks:
            return "\n".join(chunks)

    raise ValueError("No output text found in responses payload")


def call_responses_api(
    *,
    api_key: str,
    model_cfg: ModelConfig,
    system_prompt: str,
    user_prompt: str,
) -> str:
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    url = f"{model_cfg.base_url}/v1/responses"

    payload = {
        "model": model_cfg.model,
        "store": not model_cfg.disable_response_storage,
        "reasoning": {"effort": model_cfg.reasoning_effort},
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": system_prompt,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_prompt,
                    }
                ],
            },
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Model API error {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Model API network error: {exc}") from exc

    payload_obj = json.loads(raw)
    return extract_output_text(payload_obj)
