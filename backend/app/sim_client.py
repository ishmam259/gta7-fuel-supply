"""Resilient client for the BUP Fuel Supply Simulator.

Timeouts, retries with exponential backoff on 503/timeouts, a circuit breaker, stale-data detection
and schema validation. Allocation POSTs are safe to retry because they carry an idempotency key.
"""
import asyncio
import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from .config import get_settings
from .logging_setup import log_event
from .metrics import CIRCUIT_STATE, INVALID_RESPONSES, SIM_LATENCY, SIM_REQUESTS, STALE_DATA
from .sim_schemas import SCHEMAS

log = logging.getLogger("gta7.sim")


class SimulatorUnavailable(Exception):
    """Raised when the simulator cannot be reached (circuit open or retries exhausted)."""


class InvalidSimulatorResponse(Exception):
    def __init__(self, endpoint: str, detail: str):
        super().__init__(f"{endpoint}: {detail}")
        self.endpoint = endpoint
        self.detail = detail


class CircuitBreaker:
    CLOSED, HALF_OPEN, OPEN = "closed", "half_open", "open"

    def __init__(self, threshold: int, cooldown_s: float):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.state = self.CLOSED
        self.opened_at = 0.0

    def allow(self) -> bool:
        if self.state == self.OPEN and time.monotonic() - self.opened_at >= self.cooldown_s:
            self._set(self.HALF_OPEN)
        return self.state != self.OPEN

    def success(self) -> None:
        self.failures = 0
        if self.state != self.CLOSED:
            log_event(log, "circuit breaker closed", event="circuit_closed")
        self._set(self.CLOSED)

    def failure(self) -> None:
        self.failures += 1
        if self.state == self.HALF_OPEN or self.failures >= self.threshold:
            if self.state != self.OPEN:
                log_event(log, "circuit breaker opened", logging.WARNING, event="circuit_open", failures=self.failures)
            self.opened_at = time.monotonic()
            self._set(self.OPEN)

    def _set(self, state: str) -> None:
        self.state = state
        CIRCUIT_STATE.set({self.CLOSED: 0, self.HALF_OPEN: 1, self.OPEN: 2}[state])


def _endpoint_label(path: str) -> str:
    parts = path.split("?")[0].split("/")
    # collapse ids: /v1/stations/station-mirpur -> /v1/stations/{id}
    return "/".join(parts[:3]) + ("/{id}" if len(parts) > 3 else "")


class SimClient:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        # The simulator's DB pool is small (5 + 10 overflow): never hold more than a few connections at once.
        self.http = httpx.AsyncClient(base_url=s.simulator_url, timeout=s.sim_timeout_s,
                                      limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
        self._slots = asyncio.Semaphore(4)
        # separate small pool for operator/admin commands (pause, step, faults) so they are never delayed
        self._priority_http = httpx.AsyncClient(base_url=s.simulator_url, timeout=s.sim_timeout_s,
                                                limits=httpx.Limits(max_connections=2, max_keepalive_connections=2))
        self.breaker = CircuitBreaker(s.breaker_threshold, s.breaker_cooldown_s)
        self.stale = False
        self.last_error: str | None = None

    async def close(self) -> None:
        await self.http.aclose()
        await self._priority_http.aclose()

    async def _request(self, method: str, path: str, *, retry: bool = True, use_breaker: bool = True,
                       priority: bool = False, **kwargs) -> httpx.Response:
        label = _endpoint_label(path)
        if use_breaker and not self.breaker.allow():
            SIM_REQUESTS.labels(method, label, "circuit_open").inc()
            raise SimulatorUnavailable("circuit breaker open")
        attempts = self.settings.sim_retries if retry else 1
        delay = 0.25
        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            try:
                if priority:  # operator commands must not queue behind background sync reads
                    resp = await self._priority_http.request(method, path, **kwargs)
                else:
                    async with self._slots:
                        resp = await self.http.request(method, path, **kwargs)
                SIM_LATENCY.labels(label).observe(time.perf_counter() - start)
                if resp.status_code == 503:
                    SIM_REQUESTS.labels(method, label, "503").inc()
                    self.last_error = f"503 on {path}"
                    if attempt < attempts:
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue
                    if use_breaker:
                        self.breaker.failure()
                    raise SimulatorUnavailable(f"503 after {attempts} attempts on {path}")
                SIM_REQUESTS.labels(method, label, str(resp.status_code)).inc()
                if use_breaker:
                    self.breaker.success()
                if method == "GET" and path.startswith("/v1/") and not path.startswith("/v1/health"):
                    self.stale = resp.headers.get("X-Simulator-Stale", "").lower() == "true"
                    STALE_DATA.set(1 if self.stale else 0)
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                SIM_LATENCY.labels(label).observe(time.perf_counter() - start)
                SIM_REQUESTS.labels(method, label, "error").inc()
                self.last_error = f"{type(exc).__name__} on {path}"
                if attempt < attempts:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if use_breaker:
                    self.breaker.failure()
                raise SimulatorUnavailable(self.last_error) from exc
        raise SimulatorUnavailable("unreachable")

    async def get(self, path: str, params: dict | None = None) -> Any:
        resp = await self._request("GET", path, params=params)
        if resp.status_code >= 400:
            raise InvalidSimulatorResponse(path, f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            INVALID_RESPONSES.labels(_endpoint_label(path)).inc()
            raise InvalidSimulatorResponse(path, "body is not JSON")
        return self._validate(path, data)

    def _validate(self, path: str, data: Any) -> Any:
        schema = SCHEMAS.get(path.split("?")[0])
        if schema is None:
            return data
        try:
            if isinstance(data, list):
                return [schema.model_validate(x).model_dump() for x in data]
            return schema.model_validate(data).model_dump()
        except ValidationError as exc:
            INVALID_RESPONSES.labels(_endpoint_label(path)).inc()
            raise InvalidSimulatorResponse(path, str(exc.errors()[:2]))

    async def health(self) -> bool:
        """Liveness probe; bypasses faults and the breaker."""
        try:
            resp = await self._request("GET", "/v1/health", retry=False, use_breaker=False, priority=True)
            return resp.status_code == 200
        except SimulatorUnavailable:
            return False

    async def post_allocation(self, body: dict) -> tuple[int, dict]:
        """Returns (status_code, json). 201/200 = accepted; 4xx = rejected with detail.code."""
        resp = await self._request("POST", "/v1/allocations", json=body)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"detail": {"code": "INVALID_RESPONSE", "message": resp.text[:200]}}

    async def admin(self, method: str, path: str, json: dict | None = None) -> tuple[int, Any]:
        """Organizer/admin endpoints (bypass fault injection). Not behind the breaker."""
        resp = await self._request(method, path, json=json, retry=False, use_breaker=False, priority=True)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {"raw": resp.text[:500]}
