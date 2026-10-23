"""Unit tests only: transport doubles below are not experimental model results."""
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
from pathlib import Path
import pytest

from repro.budget import Budget, BudgetError, nanos_to_usd, usd_to_nanos
from repro.llm import Gateway, GatewayError, HTTPResult, sanitize

def reserve_worker(path):
    ledger = Budget(Path(path), "1", {"test": "1"})
    try:
        ledger.reserve("test", "unit.concurrent", usd_to_nanos("0.1"))
        return True
    except BudgetError:
        return False

def unit_response(text='{"ok":true}', model="gpt-4.1-mini-2025-04-14"):
    return {"id": "unit-test-response", "model": model, "status": "completed", "error": None,
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5}}

def payload():
    return {"model": "gpt-4.1-mini", "input": "Synthetic unit test room.", "max_output_tokens": 20}

def call(gateway, *, repetition="0", **kwargs):
    return gateway.responses(payload(), experiment_id="unit.test", item_id="room.1", repetition_id=repetition,
                             share="reserve", api_key="unit-test-credential", **kwargs)

def test_budget_concurrent_processes_cannot_overbook(tmp_path):
    path = str(tmp_path / "budget.sqlite3")
    Budget(Path(path), "1", {"test": "1"})
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn")) as executor:
        results = list(executor.map(reserve_worker, [path] * 15))
    assert sum(results) == 9
    summary = Budget(Path(path), "1", {"test": "1"}).summary()
    assert summary["accounted_usd"] == "0.900000000"
    assert summary["in_flight_usd"] == "0.900000000"

def test_reservation_survives_restart_and_unknown_outcome_is_charged(tmp_path):
    path = tmp_path / "budget.sqlite3"
    ledger = Budget(path, "1", {"test": "1"})
    reservation = ledger.reserve("test", "unit.crash", usd_to_nanos("0.8"))
    reopened = Budget(path, "1", {"test": "1"})
    with pytest.raises(BudgetError):
        reopened.reserve("test", "unit.next", usd_to_nanos("0.2"))
    reopened.settle(reservation, None, status="unknown_outcome")
    assert reopened.summary()["accounted_usd"] == "0.800000000"
    assert reopened.summary()["in_flight_usd"] == "0.000000000"
    with pytest.raises(BudgetError):
        reopened.settle(reservation, 0)

def test_actual_cost_releases_unused_reservation_and_policy_is_pinned(tmp_path):
    ledger = Budget(tmp_path / "budget.sqlite3", "1", {"test": "1"})
    reservation = ledger.reserve("test", "unit.actual", usd_to_nanos("0.8"))
    ledger.settle(reservation, usd_to_nanos("0.01"))
    ledger.reserve("test", "unit.next", usd_to_nanos("0.8"))
    with pytest.raises(BudgetError, match="policy"):
        Budget(tmp_path / "budget.sqlite3", "2", {"test": "1"})

def test_accounting_overrun_is_preserved_and_halts_future_calls(tmp_path):
    ledger = Budget(tmp_path / "budget.sqlite3", "1", {"test": "1"})
    reservation = ledger.reserve("test", "unit.overrun", 1)
    with pytest.raises(BudgetError):
        ledger.settle(reservation, 2)
    assert ledger.summary()["halted"]
    assert ledger.summary()["accounted_usd"] == nanos_to_usd(2)
    with pytest.raises(BudgetError):
        ledger.reserve("test", "unit.next", 1)

@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-1", "invalid"])
def test_bad_budget_is_rejected(invalid):
    with pytest.raises(BudgetError):
        usd_to_nanos(invalid)

def test_cache_is_canonical_and_distinguishes_repetitions(tmp_path):
    calls = []
    def unit_transport(**kwargs):
        calls.append(kwargs["payload"])
        return HTTPResult(200, unit_response())
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=unit_transport)
    first = call(gateway)
    assert call(gateway) == first
    assert len(calls) == 1
    reversed_payload = dict(reversed(list(payload().items())))
    assert gateway.responses(reversed_payload, experiment_id="unit.test", item_id="room.1", repetition_id="0", share="reserve",
                             api_key="unit-test-credential") == first
    call(gateway, repetition="1")
    assert len(calls) == 2
    assert len(list((tmp_path / "logs/llm_cache").glob("*.json"))) == 2

def test_replay_has_no_network_and_needs_no_key(tmp_path, monkeypatch):
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=lambda **_: HTTPResult(200, unit_response()))
    expected = call(gateway)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY_FILE", raising=False)
    def forbidden(**kwargs):
        pytest.fail("Replay attempted network")
    replay = Gateway(tmp_path, replay=True, transport_fn=forbidden)
    assert call(replay) == expected
    with pytest.raises(GatewayError, match="network access is forbidden"):
        call(replay, repetition="missing")
    with pytest.raises(GatewayError):
        replay.models()

def test_cache_tampering_is_detected(tmp_path):
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=lambda **_: HTTPResult(200, unit_response()))
    call(gateway)
    path = next((tmp_path / "logs/llm_cache").glob("*.json"))
    entry = json.loads(path.read_text())
    entry["response"]["status"] = "changed"
    path.write_text(json.dumps(entry))
    with pytest.raises(GatewayError) as error:
        call(gateway)
    assert error.value.code == "CACHE_CORRUPT"

def test_http_retries_are_capped_and_charged_conservatively(tmp_path):
    attempts, sleeps = [], []
    def unit_transport(**kwargs):
        attempts.append(1)
        return HTTPResult(503, {"error": {"message": "Synthetic unit-test failure"}})
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=unit_transport, sleep_fn=sleeps.append)
    with pytest.raises(GatewayError):
        call(gateway)
    assert len(attempts) == 5
    assert sleeps == [1, 2, 4, 8]
    rows = [json.loads(line) for line in (tmp_path / "logs/llm_calls.jsonl").read_text().splitlines()]
    errors = [row for row in rows if row["status"] == "API_ERROR"]
    assert len(errors) == 5
    assert errors[-1]["retry_count"] == 4
    upper = gateway.cost("gpt-4.1-mini", 1047576, 20)
    assert gateway.budget.summary()["accounted_usd"] == nanos_to_usd(5 * upper)
    with pytest.raises(GatewayError):
        call(gateway)
    assert len(attempts) == 5

def test_network_exception_is_sanitized_and_never_automatically_retried(tmp_path):
    secret = "sk-" + "x" * 30
    attempts = []
    def unit_transport(**kwargs):
        attempts.append(1)
        raise RuntimeError("Failure with " + secret + " and unit-test-credential")
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=unit_transport)
    with pytest.raises(GatewayError) as error:
        call(gateway)
    assert secret not in str(error.value)
    assert len(attempts) == 1
    assert gateway.budget.summary()["accounted_usd"] != "0.000000000"
    for path in (tmp_path / "logs").rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl"}:
            assert secret not in path.read_text()
            assert "unit-test-credential" not in path.read_text()

def test_response_redaction_and_request_secret_refusal(tmp_path):
    secret = "sk-" + "s" * 30
    text = "Echo " + secret + " Bear" + "er fake-token unit-test-credential"
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=lambda **_: HTTPResult(200, unit_response(text)))
    response = call(gateway)
    assert secret not in json.dumps(response)
    assert "fake-token" not in json.dumps(response)
    assert "unit-test-credential" not in json.dumps(response)
    with pytest.raises(GatewayError) as error:
        gateway.responses({**payload(), "input": secret}, experiment_id="unit.test", item_id="secret", repetition_id=0,
                          share="reserve", api_key="unit-test-credential")
    assert error.value.code == "SECRET_IN_REQUEST"
    assert sanitize({"authorization": secret}) == {"[REDACTED_FIELD]": "[REDACTED]"}

@pytest.mark.parametrize("override,code", [
    ({"model": "unpriced-model"}, "UNPRICED_MODEL"),
    ({"tools": [{"type": "web_search"}]}, "UNPRICED_TOOL"),
    ({"previous_response_id": "prior"}, "UNSUPPORTED_REQUEST"),
    ({"service_tier": "priority"}, "UNSUPPORTED_REQUEST"),
    ({"input": [{"role": "user", "content": [{"type": "input_image", "image_url": "https://example.invalid/image"}]}]}, "TEXT_ONLY")
])
def test_unaccountable_requests_are_refused_before_network(tmp_path, override, code):
    def forbidden(**kwargs):
        pytest.fail("Invalid request contacted API")
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=forbidden)
    with pytest.raises(GatewayError) as error:
        gateway.responses({**payload(), **override}, experiment_id="unit.test", item_id="invalid", repetition_id=0,
                          share="reserve", api_key="unit-test-credential")
    assert error.value.code == code

def test_missing_usage_halts_ledger_and_retains_reservation(tmp_path):
    body = unit_response()
    del body["usage"]
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=lambda **_: HTTPResult(200, body))
    with pytest.raises(GatewayError) as error:
        call(gateway)
    assert error.value.code == "UNACCOUNTABLE_RESPONSE"
    assert gateway.budget.summary()["halted"]
    assert gateway.budget.summary()["accounted_usd"] != "0.000000000"



def test_exact_count_enables_small_allocation_and_includes_schema(tmp_path):
    calls = []
    def unit_transport(**kwargs):
        calls.append(kwargs)
        if kwargs["path"] == "/responses/input_tokens":
            return HTTPResult(200, {"object": "response.input_tokens", "input_tokens": 10})
        return HTTPResult(200, unit_response())
    gateway = Gateway(tmp_path, max_usd="0.01", transport_fn=unit_transport, count_input_tokens=True)
    assert call(gateway)["status"] == "completed"
    assert [row["path"] for row in calls] == ["/responses/input_tokens", "/responses"]
    assert gateway.budget.summary()["accounted_usd"] == "0.000012000"
    call(gateway)
    assert len(calls) == 2

def test_failed_token_count_never_generates(tmp_path):
    calls = []
    def unit_transport(**kwargs):
        calls.append(kwargs)
        return HTTPResult(404, {"error": {"message": "unit unsupported endpoint"}})
    gateway = Gateway(tmp_path, max_usd="0.01", transport_fn=unit_transport, count_input_tokens=True)
    with pytest.raises(GatewayError) as error:
        call(gateway)
    assert error.value.code == "TOKEN_COUNT_ERROR"
    assert [row["path"] for row in calls] == ["/responses/input_tokens"]
    assert gateway.budget.summary()["accounted_usd"] == "0.000000000"

def test_input_count_mismatch_halts_future_requests(tmp_path):
    def unit_transport(**kwargs):
        if kwargs["path"] == "/responses/input_tokens":
            return HTTPResult(200, {"object": "response.input_tokens", "input_tokens": 1})
        return HTTPResult(200, unit_response())
    gateway = Gateway(tmp_path, max_usd="100", transport_fn=unit_transport, count_input_tokens=True)
    with pytest.raises(GatewayError):
        call(gateway)
    assert gateway.budget.summary()["halted"]



def test_input_ceiling_refuses_generation_without_stranding_claim(tmp_path):
    paths=[]
    def unit_transport(**kwargs):
        paths.append(kwargs["path"])
        if kwargs["path"]=="/responses/input_tokens":
            return HTTPResult(200,{"object":"response.input_tokens","input_tokens":10})
        return HTTPResult(200,unit_response())
    gateway=Gateway(tmp_path,max_usd="1",transport_fn=unit_transport,count_input_tokens=True)
    with pytest.raises(GatewayError) as error: call(gateway,max_input_tokens=9)
    assert error.value.code=="INPUT_TOKEN_LIMIT"
    assert paths==["/responses/input_tokens"]
    assert gateway.budget.summary()["accounted_usd"]=="0.000000000"
    assert call(gateway,max_input_tokens=10)["status"]=="completed"
    assert paths==["/responses/input_tokens","/responses/input_tokens","/responses"]

