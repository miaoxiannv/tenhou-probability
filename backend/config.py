from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    provider_name: str = "OpenAI"
    base_url: str = "http://sub2api.chenlabs.online"
    wire_api: str = "responses"
    model: str = "gpt-5.3-codex"
    review_model: str = "gpt-5.3-codex"
    reasoning_effort: str = "xhigh"
    disable_response_storage: bool = True
    network_access: str = "enabled"
    enable_legacy_backend_render: bool = False


@dataclass
class AppConfig:
    api_key: str | None
    model: ModelConfig


def _first_non_empty_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def load_config() -> AppConfig:
    model_cfg = ModelConfig(
        base_url=os.getenv("SUB2API_BASE_URL", "http://sub2api.chenlabs.online").rstrip("/"),
        model=os.getenv("MODEL_NAME", "gpt-5.3-codex"),
        review_model=os.getenv("REVIEW_MODEL_NAME", "gpt-5.3-codex"),
        reasoning_effort=os.getenv("MODEL_REASONING_EFFORT", "xhigh"),
        disable_response_storage=(os.getenv("DISABLE_RESPONSE_STORAGE", "true").lower() == "true"),
        network_access=os.getenv("MODEL_NETWORK_ACCESS", "enabled"),
        enable_legacy_backend_render=(os.getenv("ENABLE_LEGACY_BACKEND_RENDER", "false").lower() == "true"),
    )

    return AppConfig(
        api_key=_first_non_empty_env("OPENAI_API_KEY", "SUB2API_API_KEY"),
        model=model_cfg,
    )
