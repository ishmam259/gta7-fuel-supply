"""Resilient simulator client: retries, circuit breaker, validation, stale-data detection."""
import asyncio

import httpx
import pytest

from app.sim_client import CircuitBreaker, InvalidSimulatorResponse, SimClient, SimulatorUnavailable

INSTANCE = {"id": 1, "tick": 5, "sim_time": "2026-01-01T01:15:00", "tick_minutes": 15, "status": "PAUSED"}


def make_client(handler) -> SimClient:
    c = SimClient()
    c.http = httpx.AsyncClient(base_url="http://sim", transport=httpx.MockTransport(handler))
    c._priority_http = httpx.AsyncClient(base_url="http://sim", transport=httpx.MockTransport(handler))
    c.breaker = CircuitBreaker(threshold=2, cooldown_s=0.05)
    return c


def run(coro):
    return asyncio.run(coro)


def test_retries_503_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"code": "FAULT_INJECTED"}})
        return httpx.Response(200, json=INSTANCE)

    c = make_client(handler)
    assert run(c.get("/v1/instance"))["tick"] == 5
    assert calls["n"] == 3
    assert c.breaker.state == "closed"


def test_breaker_opens_after_repeated_failures_and_recovers():
    state = {"down": True}

    def handler(req):
        if state["down"]:
            return httpx.Response(503, json={"error": {"code": "FAULT_INJECTED"}})
        return httpx.Response(200, json=INSTANCE)

    c = make_client(handler)
    for _ in range(2):
        with pytest.raises(SimulatorUnavailable):
            run(c.get("/v1/instance"))
    assert c.breaker.state == "open"
    # while open, calls fail fast without hitting the simulator
    with pytest.raises(SimulatorUnavailable, match="circuit breaker open"):
        run(c.get("/v1/instance"))
    state["down"] = False
    run(asyncio.sleep(0.06))  # cooldown -> half-open probe
    assert run(c.get("/v1/instance"))["tick"] == 5
    assert c.breaker.state == "closed"


def test_timeouts_become_simulator_unavailable():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    c = make_client(handler)
    with pytest.raises(SimulatorUnavailable):
        run(c.get("/v1/instance"))


def test_invalid_response_is_rejected():
    def handler(req):
        return httpx.Response(200, json={"tick": -3, "status": "EXPLODED"})

    c = make_client(handler)
    with pytest.raises(InvalidSimulatorResponse):
        run(c.get("/v1/instance"))


def test_non_json_body_is_rejected():
    c = make_client(lambda req: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(InvalidSimulatorResponse):
        run(c.get("/v1/instance"))


def test_stale_header_detected_but_not_reset_by_health_probe():
    def handler(req):
        if req.url.path == "/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json=INSTANCE, headers={"X-Simulator-Stale": "true"})

    c = make_client(handler)
    run(c.get("/v1/instance"))
    assert c.stale is True
    assert run(c.health()) is True
    assert c.stale is True  # health bypasses faults, must not clear the flag


def test_allocation_conflict_returns_code_without_retry():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(409, json={"detail": {"code": "INSUFFICIENT_INVENTORY", "message": "no fuel"}})

    c = make_client(handler)
    code, body = run(c.post_allocation({"idempotency_key": "k"}))
    assert code == 409 and body["detail"]["code"] == "INSUFFICIENT_INVENTORY"
    assert calls["n"] == 1
