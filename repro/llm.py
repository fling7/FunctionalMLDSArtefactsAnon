"""Budgeted text-only Responses API gateway, deterministic cache, and offline replay."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import uuid

from repro.budget import Budget, BudgetError, nanos_to_usd, utc_now
from repro import env as _credential_env
ROOT = getattr(_credential_env, 'ROOT')
get_key = getattr(_credential_env, 'get_key')
load_env = getattr(_credential_env, 'load_env')

API_BASE = "https://api.openai.com/v1"
SECRET_PATTERN = re.compile('sk-[A-Za-z0-9_-]{12,}')
AUTH_PATTERN = re.compile('(?i)bearer\\s+[^\\s\\"\'<>,;]+')
ENV_PATTERN = re.compile('(?i)OPENAI_API_KEY\\s*=\\s*[^\\s\\"\'<>]+')
SECRET_FIELDS = {"authorization", "api_key", "openai_api_key", "openai_api_key_file", "access_token", "secret"}
SAFE_ID = re.compile('[A-Za-z0-9_.:/-]{1,240}\\Z')

class GatewayError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

def sha256(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

def sanitize(value, secrets=()):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = SECRET_PATTERN.sub("[REDACTED]", value)
        value = AUTH_PATTERN.sub("[AUTH_REDACTED]", value)
        return ENV_PATTERN.sub("[CREDENTIAL_ASSIGNMENT_REDACTED]", value)
    if isinstance(value, dict):
        return {("[REDACTED_FIELD]" if str(k).lower() in SECRET_FIELDS else sanitize(str(k), secrets)):
                ("[REDACTED]" if str(k).lower() in SECRET_FIELDS else sanitize(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, secrets) for v in value]
    return value

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)

@dataclass
class HTTPResult:
    status: int
    body: dict
    request_id: str | None = None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def transport(*, method: str, path: str, payload: dict | None, key: str, timeout: float) -> HTTPResult:
    """Only fixed official endpoints; credentials are never included in errors."""
    if path not in {"/responses", "/models", "/responses/input_tokens"}:
        raise GatewayError("ENDPOINT", "Unsupported API endpoint.")
    request = urllib.request.Request(API_BASE + path, data=canonical_bytes(payload) if payload is not None else None,
                                     headers={"Authorization": "Bearer\x20" + key, "Content-Type": "application/json"}, method=method)
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    except Exception:
        raise GatewayError("NETWORK_ERROR", "API network request failed; credentials and raw exception omitted.") from None
    try:
        with response:
            raw = response.read()
            status = response.status
            request_id = response.headers.get("x-request-id")
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            body = {"error": {"type": "NON_JSON_RESPONSE", "message": raw[:2048].decode("utf-8", errors="replace")}}
        if not isinstance(body, dict):
            body = {"error": {"type": "INVALID_RESPONSE_SHAPE"}}
        return HTTPResult(status, body, request_id)
    except Exception:
        raise GatewayError("NETWORK_ERROR", "API response could not be read; outcome unknown.") from None

class Gateway:
    def __init__(self, root: Path = ROOT, *, replay=False, max_usd=None, transport_fn=None, sleep_fn=None, timeout=60, count_input_tokens=False):
        self.root = Path(root)
        self.replay = replay
        self.logs = self.root / "logs"
        self.cache = self.logs / "llm_cache"
        exported_cache = self.root / "data" / "llm_cache"
        if replay and not self.cache.is_dir() and exported_cache.is_dir():
            self.cache = exported_cache
        self.prices = json.loads((Path(__file__).with_name("prices.json")).read_text(encoding="utf-8-sig"))["models"]
        self._transport = transport_fn or transport
        self._sleep = sleep_fn or time.sleep
        self.timeout = timeout
        self.count_input_tokens = count_input_tokens
        self.budget = None
        if not replay:
            load_env(self.root)
            self.budget = Budget(self.logs / "api_budget.sqlite3", max_usd if max_usd is not None else os.environ.get("MAX_API_COST_USD", "100"))

    def _price(self, model: str) -> dict:
        if model not in self.prices:
            raise GatewayError("UNPRICED_MODEL", "Model is not in the verified price registry; register its official rates before use.")
        return self.prices[model]

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        price = self._price(model)
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
            raise GatewayError("INVALID_USAGE", "Token usage must contain non-negative integers.")
        # USD per million multiplied by 1000 yields nanodollars per token.
        amount = (Decimal(price["input_per_million"]) * input_tokens + Decimal(price["output_per_million"]) * output_tokens) * 1000
        return int(amount.to_integral_value(rounding=ROUND_CEILING))

    def prepare(self, payload: dict) -> dict:
        payload = json.loads(canonical_bytes(payload))
        allowed = {"model", "input", "instructions", "temperature", "top_p", "max_output_tokens", "text", "tools",
                   "tool_choice", "parallel_tool_calls", "store", "metadata", "stream", "background", "truncation", "service_tier"}
        if set(payload) - allowed:
            raise GatewayError("UNSUPPORTED_REQUEST", "Request contains unsupported fields or server-side history.")
        price = self._price(payload.get("model", ""))
        if payload.get("stream") or payload.get("background") or payload.get("service_tier", "default") != "default":
            raise GatewayError("UNSUPPORTED_REQUEST", "Streaming, background mode, and nonstandard service tiers are prohibited.")
        payload["store"] = False
        payload["service_tier"] = "default"
        payload.setdefault("max_output_tokens", 2048)
        limit = payload["max_output_tokens"]
        if type(limit) is not int or not 1 <= limit <= price["max_output_tokens"]:
            raise GatewayError("OUTPUT_LIMIT", "A valid bounded max_output_tokens value is required.")
        inputs = payload.get("input")
        if not isinstance(inputs, (str, list)) or inputs == []:
            raise GatewayError("TEXT_ONLY", "Input must be text or a nonempty inline message list.")
        if isinstance(inputs, list):
            for message in inputs:
                if not isinstance(message, dict) or set(message) - {"role", "content", "type"} or message.get("type", "message") != "message":
                    raise GatewayError("TEXT_ONLY", "Only inline text messages are supported.")
                if message.get("role") not in {"user", "assistant", "system", "developer"}:
                    raise GatewayError("TEXT_ONLY", "Unsupported message role.")
                content = message.get("content")
                if isinstance(content, str):
                    continue
                if not isinstance(content, list):
                    raise GatewayError("TEXT_ONLY", "Only inline text message content is supported.")
                if any(not isinstance(part, dict) or set(part) - {"type", "text"} or part.get("type") != "input_text" or not isinstance(part.get("text"), str) for part in content):
                    raise GatewayError("TEXT_ONLY", "Images, files, references and other modalities are prohibited.")
        for tool in payload.get("tools", []):
            if not isinstance(tool, dict) or tool.get("type") != "function":
                raise GatewayError("UNPRICED_TOOL", "Hosted tools and their additional charges are prohibited.")
        return payload

    def _record(self, record, secrets=()):
        self.budget.record(sanitize(record, secrets), self.logs / "llm_calls.jsonl")

    def _cache_read(self, path: Path, cache_key: str, envelope: dict):
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored["cache_key"] != cache_key or stored["canonical_request"] != envelope:
                raise ValueError
            if sha256(stored["response"]) != stored["response_sha256"]:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise GatewayError("CACHE_CORRUPT", "Cache entry failed content or request hash validation.") from None
        if stored["status"] != "SUCCESS":
            raise GatewayError("API_ERROR", "Recorded API failure replayed; inspect sanitized call log.")
        return stored["response"]

    def responses(self, payload: dict, *, experiment_id: str, item_id: str, repetition_id: str | int,
                  share: str, api_key: str | None = None, max_attempts: int = 5, max_input_tokens: int | None = None) -> dict:
        """Return API JSON; repetition identity is mandatory and is never sent to OpenAI."""
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise GatewayError("RETRY_LIMIT", "One through five total attempts are allowed.")
        repetition_id = str(repetition_id)
        for value in (experiment_id, item_id, repetition_id):
            if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
                raise GatewayError("IDENTITY", "Experiment, item and repetition IDs must be nonempty safe identifiers.")
        payload = self.prepare(payload)
        key = "" if self.replay else (api_key if api_key is not None else get_key())
        secrets = (key,) if key else ()
        envelope = {"version": 1, "endpoint": API_BASE + "/responses", "experiment_id": experiment_id,
                    "item_id": item_id, "repetition_id": repetition_id, "share": share, "payload": payload}
        if sanitize(envelope, secrets) != envelope:
            raise GatewayError("SECRET_IN_REQUEST", "Credential-like material detected in request or identity; request refused.")
        cache_key = sha256(envelope)
        cache_path = self.cache / (cache_key + ".json")
        base = {"timestamp": utc_now(), "experiment_id": experiment_id, "item_id": item_id, "repetition_id": repetition_id,
                "share": share, "cache_key": cache_key, "requested_model": payload["model"],
                "parameters": {k: v for k, v in payload.items() if k not in {"input", "instructions"}},
                "prompt_hash": sha256({"input": payload["input"], "instructions": payload.get("instructions")})}
        if cache_path.is_file():
            response = self._cache_read(cache_path, cache_key, envelope)
            if not self.replay:
                self._record({**base, "status": "CACHE_HIT", "returned_model": response.get("model"), "usage": response.get("usage"),
                              "latency_seconds": 0, "cost_usd": "0.000000000", "response": response}, secrets)
            return response
        if self.replay:
            raise GatewayError("REPLAY_MISS", "Replay cache entry missing; network access is forbidden.")
        if not key:
            raise GatewayError("MISSING_KEY", "No API credential configured.")
        price = self._price(payload["model"])
        input_bound = self._count_input(payload, key, base, max_attempts) if self.count_input_tokens else price["context_window"]
        base["reservation_basis"] = "provider_input_count" if self.count_input_tokens else "full_context_window"
        base["input_token_bound"] = input_bound
        if max_input_tokens is not None:
            if type(max_input_tokens) is not int or max_input_tokens < 1 or not self.count_input_tokens:
                raise GatewayError("INPUT_TOKEN_LIMIT", "Input ceilings require exact provider token counting and a positive integer limit.")
            if input_bound > max_input_tokens:
                self._record({**base, "status": "INPUT_LIMIT", "input_token_ceiling": max_input_tokens,
                              "cost_usd": "0.000000000"}, secrets)
                raise GatewayError("INPUT_TOKEN_LIMIT", "Exact input count exceeds the preregistered ceiling; no generation attempted.")
        if not self.budget.claim(cache_key):
            raise GatewayError("REQUEST_ALREADY_CLAIMED", "Request already pending or interrupted; reconcile before retrying. Never change repetition identity to bypass an unknown outcome.")
        # Full input context is an actual upper bound. No character/token heuristic.
        upper = self.cost(payload["model"], input_bound, payload["max_output_tokens"])
        for attempt in range(1, max_attempts + 1):
            try:
                reservation = self.budget.reserve(share, experiment_id, upper)
            except BudgetError:
                self._record({**base, "status": "BUDGET_STOP", "attempt": attempt, "cost_usd": "0.000000000"}, secrets)
                self.budget.finish_claim(cache_key, "budget_stop")
                raise
            started = time.perf_counter()
            self._record({**base, "status": "ATTEMPT_STARTED", "attempt": attempt, "reservation_id": reservation, "reserved_usd": nanos_to_usd(upper)}, secrets)
            result = None
            failure_code = None
            try:
                result = self._transport(method="POST", path="/responses", payload=payload, key=key, timeout=self.timeout)
            except Exception as exc:
                failure_code = exc.code if isinstance(exc, GatewayError) else "NETWORK_ERROR"
            latency = time.perf_counter() - started
            if result is None:
                charged = self.budget.settle(reservation, None, status="unknown_outcome")
                response = {"error": {"type": failure_code}}
                self._record({**base, "status": "API_ERROR", "attempt": attempt, "retry_count": attempt - 1,
                              "outcome": "unknown", "response": response, "latency_seconds": latency,
                              "cost_usd": nanos_to_usd(charged), "cost_basis": "full_reservation"}, secrets)
                self._save_cache(cache_path, cache_key, envelope, response, "API_ERROR", secrets)
                self.budget.finish_claim(cache_key, "error")
                raise GatewayError(failure_code, "API request failed with unknown outcome; reservation charged and no automatic retry.") from None
            response = sanitize(result.body, secrets)
            usage = response.get("usage")
            successful = 200 <= result.status < 300 and not response.get("error")
            actual = None
            if successful:
                try:
                    actual = self.cost(response.get("model", ""), usage["input_tokens"], usage["output_tokens"])
                except (GatewayError, KeyError, TypeError):
                    failure_code = "UNACCOUNTABLE_RESPONSE"
                    self.budget.halt()
                    successful = False
                if actual is not None and (usage["input_tokens"] > input_bound or usage["output_tokens"] > payload["max_output_tokens"]):
                    failure_code = "TOKEN_BOUND_EXCEEDED"
                    self.budget.halt()
                    successful = False
            try:
                charged = self.budget.settle(reservation, actual, status="completed" if successful else "api_error")
            except BudgetError:
                failure_code = "COST_BOUND_EXCEEDED"
                charged = actual
                successful = False
            record = {**base, "status": "SUCCESS" if successful else "API_ERROR", "attempt": attempt,
                      "retry_count": attempt - 1, "http_status": result.status, "request_id": result.request_id,
                      "returned_model": response.get("model"), "response": response, "usage": usage,
                      "latency_seconds": latency, "cost_usd": nanos_to_usd(charged),
                      "cost_basis": "reported_tokens" if actual is not None else "full_reservation"}
            self._record(record, secrets)
            retryable = not successful and failure_code is None and (result.status == 429 or 500 <= result.status < 600)
            if retryable and attempt < max_attempts:
                self._sleep(min(2 ** (attempt - 1), 16))
                continue
            status = "SUCCESS" if successful else "API_ERROR"
            self._save_cache(cache_path, cache_key, envelope, response, status, secrets)
            self.budget.finish_claim(cache_key, "complete" if successful else "error")
            if not successful:
                raise GatewayError(failure_code or "API_ERROR", "API call failed; inspect sanitized logs for HTTP status and retry count.") from None
            return response
        raise AssertionError("unreachable")

    def _save_cache(self, path, cache_key, envelope, response, status, secrets):
        response = sanitize(response, secrets)
        atomic_json(path, {"cache_key": cache_key, "canonical_request": sanitize(envelope, secrets), "status": status,
                           "response": response, "response_sha256": sha256(response), "saved_at": utc_now()})

    def _count_input(self, payload, key, base, max_attempts):
        """Official endpoint counts message framing and schema tokens before generation."""
        fields = {"model", "input", "instructions", "text", "tools", "tool_choice", "parallel_tool_calls", "truncation"}
        count_payload = {name: value for name, value in payload.items() if name in fields}
        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                result = self._transport(method="POST", path="/responses/input_tokens", payload=count_payload, key=key, timeout=self.timeout)
            except Exception:
                self._record({**base, "endpoint": "/responses/input_tokens", "status": "TOKEN_COUNT_ERROR",
                              "attempt": attempt, "cost_usd": "0.000000000", "error": "NETWORK_ERROR"}, (key,))
                raise GatewayError("TOKEN_COUNT_ERROR", "Input token count unavailable; no generation attempted.") from None
            body = sanitize(result.body, (key,))
            count = body.get("input_tokens")
            valid = result.status == 200 and body.get("object") == "response.input_tokens" and type(count) is int and 0 <= count <= self._price(payload["model"])["context_window"]
            self._record({**base, "endpoint": "/responses/input_tokens", "status": "TOKEN_COUNT" if valid else "TOKEN_COUNT_ERROR",
                          "attempt": attempt, "http_status": result.status, "response": body,
                          "latency_seconds": time.perf_counter() - started, "cost_usd": "0.000000000",
                          "cost_basis": "non_generation_token_count_endpoint"}, (key,))
            if valid:
                return count
            if (result.status == 429 or 500 <= result.status < 600) and attempt < max_attempts:
                self._sleep(min(2 ** (attempt - 1), 16))
                continue
            raise GatewayError("TOKEN_COUNT_ERROR", "Input token count unavailable or invalid; no generation attempted.")

    def models(self, *, api_key=None, max_attempts=5) -> dict:
        if self.replay:
            raise GatewayError("REPLAY_NETWORK", "Model discovery is forbidden in replay mode.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise GatewayError("RETRY_LIMIT", "One through five total attempts are allowed.")
        key = api_key if api_key is not None else get_key()
        if not key:
            raise GatewayError("MISSING_KEY", "No API credential configured.")
        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                result = self._transport(method="GET", path="/models", payload=None, key=key, timeout=self.timeout)
            except Exception:
                self._record({"timestamp": utc_now(), "experiment_id": "WP0.preflight", "endpoint": "/models",
                              "status": "API_ERROR", "attempt": attempt, "error": "NETWORK_ERROR", "cost_usd": "0.000000000"}, (key,))
                raise GatewayError("NETWORK_ERROR", "Model discovery network request failed.") from None
            body = sanitize(result.body, (key,))
            self._record({"timestamp": utc_now(), "experiment_id": "WP0.preflight", "endpoint": "/models",
                          "status": "SUCCESS" if result.status == 200 else "API_ERROR", "attempt": attempt,
                          "http_status": result.status, "response": body, "latency_seconds": time.perf_counter() - started,
                          "cost_usd": "0.000000000"}, (key,))
            if result.status == 200 and isinstance(body.get("data"), list):
                return body
            if (result.status == 429 or 500 <= result.status < 600) and attempt < max_attempts:
                self._sleep(min(2 ** (attempt - 1), 16))
                continue
            raise GatewayError("MODELS_HTTP_" + str(result.status), "Model discovery failed; inspect sanitized logs.")




# Opt-in production integration. ContextVar isolates concurrent experiment threads.
from contextlib import contextmanager
from contextvars import ContextVar
_EXPERIMENT_CONTEXT = ContextVar("llm_experiment_context", default=None)

@contextmanager
def experiment_context(*, experiment_id, item_id, repetition_id, share, stage_id="call", root=ROOT,
                       replay=False, max_output_tokens=4096, model=None, temperature=None, max_input_tokens=None,
                       before_call=None, after_call=None):
    context = {"experiment_id": experiment_id, "item_id": item_id, "repetition_id": str(repetition_id),
               "share": share, "stage_id": stage_id, "root": Path(root), "replay": replay,
               "max_output_tokens": max_output_tokens, "model": model, "call_index": 0,
               "temperature": temperature, "max_input_tokens": max_input_tokens,
               "before_call": before_call, "after_call": after_call}
    token = _EXPERIMENT_CONTEXT.set(context)
    try:
        yield context
    finally:
        _EXPERIMENT_CONTEXT.reset(token)

def production_response(payload, *, api_key=None, timeout=60, source="production"):
    """Hook used only when ROOMCONTRACT_LLM_GATEWAY=1; never falls back."""
    context = _EXPERIMENT_CONTEXT.get()
    if context is None:
        required = {"experiment_id": "LLM_EXPERIMENT_ID", "item_id": "LLM_ITEM_ID",
                    "repetition_id": "LLM_REPETITION_ID", "share": "LLM_BUDGET_SHARE"}
        if any(not os.environ.get(env) for env in required.values()):
            raise GatewayError("MISSING_EXPERIMENT_IDENTITY", "Gateway hook requires an experiment context or explicit identity environment variables.")
        context = {name: os.environ[env] for name, env in required.items()}
        context.update({"root": ROOT, "replay": os.environ.get("LLM_REPLAY") == "1",
                        "stage_id": source, "call_index": 0, "max_output_tokens": 4096, "model": None})
    else:
        context["call_index"] += 1
    bounded = dict(payload)
    bounded["max_output_tokens"] = min(int(bounded.get("max_output_tokens", context["max_output_tokens"])), int(context["max_output_tokens"]))
    if context["model"]:
        bounded["model"] = context["model"]
    if context.get("temperature") is not None:
        bounded["temperature"] = context["temperature"]
    if context.get("before_call"):
        context["before_call"](context["call_index"], bounded)
    gateway = Gateway(context["root"], replay=context["replay"], timeout=timeout, count_input_tokens=True)
    suffix = f"{context['stage_id']}.attempt{context['call_index']:02d}"
    try:
        response = gateway.responses(bounded, experiment_id=context["experiment_id"], item_id=context["item_id"] + "." + suffix,
                                     repetition_id=context["repetition_id"], share=context["share"], api_key=api_key,
                                     max_input_tokens=context.get("max_input_tokens"))
    except (GatewayError, BudgetError) as exc:
        if context.get("after_call"):
            context["after_call"](context["call_index"], {"gateway_error": getattr(exc, "code", "BUDGET_STOP")})
        raise
    if context.get("after_call"):
        context["after_call"](context["call_index"], response)
    return response

