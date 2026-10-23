from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_BACKEND_CONFIG = Path(
    "app/backend_root/agent_backend/config.json"
)


class LlmStageError(RuntimeError):
    pass


def _env_text(name: str) -> Optional[str]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _load_api_key(config: Dict[str, Any]) -> str:
    direct_key = _env_text("OPENAI_API_KEY")
    key_file = _env_text("OPENAI_API_KEY_FILE")
    if direct_key and key_file:
        raise LlmStageError(
            "OPENAI_API_KEY and OPENAI_API_KEY_FILE must not both be set."
        )
    if direct_key:
        return direct_key
    if key_file:
        secret_path = Path(key_file)
        try:
            secret = secret_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise LlmStageError(
                f"OPENAI_API_KEY_FILE could not be read: {secret_path}"
            ) from exc
        if not secret:
            raise LlmStageError("OPENAI_API_KEY_FILE is empty.")
        return secret

    configured = str(config.get("openai_api_key") or "").strip()
    if not configured:
        raise LlmStageError(
            "No OpenAI API key configured via environment, secret file, or backend config."
        )
    return configured


def sanitize_error_text(text: Any) -> str:
    cleaned = str(text)
    cleaned = re.sub('sk-[A-Za-z0-9_-]+', "[REDACTED_API_KEY]", cleaned)
    cleaned = re.sub('Bearer\\s+[A-Za-z0-9._-]+', "Bearer\x20[REDACTED_API_KEY]", cleaned)
    return cleaned


def _extract_output_text(resp: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in resp.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text":
                parts.append(str(content.get("text", "")))
    return "\n".join(p for p in parts if p).strip()


def _prefer_mini_model(model: str) -> str:
    low = (model or "").strip()
    replacements = {
        "gpt-4.1": "gpt-4.1-mini",
        "gpt-4o": "gpt-4o-mini",
        "gpt-5": "gpt-5-mini",
        "gpt-5.1": "gpt-5.1-codex-mini",
    }
    return replacements.get(low, low or "gpt-4.1-mini")


@dataclass(frozen=True)
class LlmSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int
    config_path: Path

    def redacted_metadata(self) -> Dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout_seconds": self.timeout_seconds,
            "config_path": str(self.config_path),
            "api_key_present": bool(self.api_key),
        }


def load_llm_settings(
    *,
    config_path: Path = DEFAULT_BACKEND_CONFIG,
    model_override: Optional[str] = None,
    prefer_low_token_model: bool = True,
) -> LlmSettings:
    if os.environ.get("ROOMCONTRACT_LLM_GATEWAY") == "1" and os.environ.get("LLM_REPLAY") != "1":
        from repro import env as _credential_env
        load_env = getattr(_credential_env, 'load_env')
        load_env()
    config_path = _resolve_backend_config_path(config_path)
    if not config_path.exists():
        raise LlmStageError(f"Backend config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    api_key = "" if os.environ.get("ROOMCONTRACT_LLM_GATEWAY") == "1" and os.environ.get("LLM_REPLAY") == "1" else _load_api_key(config)

    configured_model = (
        model_override
        or os.environ.get("CASE_STUDY_OPENAI_MODEL")
        or str(config.get("case_study_model") or config.get("model") or "gpt-4.1-mini")
    )
    model = _prefer_mini_model(configured_model) if prefer_low_token_model and not model_override else configured_model

    return LlmSettings(
        api_key=api_key,
        base_url=str(config.get("openai_base_url") or "https://api.openai.com/v1/responses"),
        model=model,
        timeout_seconds=int(config.get("timeout_seconds") or 60),
        config_path=config_path,
    )


def _resolve_backend_config_path(config_path: Path) -> Path:
    resolved = config_path.resolve()
    if resolved.exists():
        return resolved

    cwd = Path.cwd().resolve()
    local_backend_config = cwd / "config.json"
    if cwd.name == "agent_backend" and local_backend_config.exists():
        return local_backend_config

    for parent in (cwd, *cwd.parents):
        candidate = parent / DEFAULT_BACKEND_CONFIG
        if candidate.exists():
            return candidate.resolve()

    for parent in resolved.parents:
        if parent.name == "agent_backend":
            candidate = parent / "config.json"
            if candidate.exists():
                return candidate.resolve()

    return resolved


@dataclass
class ResponsesClient:
    settings: LlmSettings

    def create_structured_json(
        self,
        *,
        input_messages: List[Dict[str, Any]],
        schema: Dict[str, Any],
        schema_name: str,
        temperature: float = 0.2,
        max_output_tokens: int = 1800,
    ) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
        payload: Dict[str, Any] = {
            "model": self.settings.model,
            "input": input_messages,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if os.environ.get("ROOMCONTRACT_LLM_GATEWAY") == "1":
            from repro.llm import production_response, GatewayError
            from repro.budget import BudgetError
            try:
                response_payload = production_response(payload, api_key=self.settings.api_key,
                                                       timeout=self.settings.timeout_seconds, source="pipeline")
            except (GatewayError, BudgetError) as exc:
                raise LlmStageError("Budgeted gateway stopped request: " + getattr(exc, "code", "BUDGET_STOP")) from None
        else:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                self.settings.base_url,
                data=raw,
                method="POST",
                headers={
                    "Authorization": f"Bearer\x20{self.settings.api_key}",
                    "Content-Type": "application/json",
                },
            )

            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                    response_payload = json.loads(response.read().decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="replace")
                raise LlmStageError(f"OpenAI HTTP {exc.code}: {sanitize_error_text(details)[:1200]}") from exc
            except urllib.error.URLError as exc:
                raise LlmStageError(f"OpenAI connection error: {sanitize_error_text(exc)}") from exc

        output_text = _extract_output_text(response_payload)
        try:
            parsed = json.loads(output_text) if output_text else {}
        except json.JSONDecodeError as exc:
            raise LlmStageError(f"Structured output was not valid JSON: {exc}") from exc
        return parsed, response_payload, output_text


def response_metadata(response_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "response_id": response_payload.get("id"),
        "model": response_payload.get("model"),
        "status": response_payload.get("status"),
        "usage": response_payload.get("usage") or {},
    }
