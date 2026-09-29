import os
import sys
import requests

SIMULATOR_URL = os.getenv("SIMULATOR_URL", "http://localhost:8000")


def request(method: str, path: str, **kwargs):
    url = f"{SIMULATOR_URL}{path}"

    try:
        response = requests.request(
            method,
            url,
            timeout=10,
            **kwargs,
        )

        print(f"{method} {path} -> {response.status_code}")

        response.raise_for_status()

        if response.content:
            return response.json()

        return None

    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        sys.exit(1)


def get_instance():
    return request("GET", "/v1/instance")


def get_metrics():
    return request("GET", "/v1/metrics")


def get_stations():
    return request("GET", "/v1/stations")


def get_depots():
    return request("GET", "/v1/depots")


def get_routes():
    return request("GET", "/v1/routes")


def get_events():
    return request("GET", "/v1/events")


def get_allocations():
    return request("GET", "/v1/allocations")


def reset():
    print("\nResetting simulator...")
    return request("POST", "/admin/reset")


def pause():
    print("\nPausing simulator...")
    return request("POST", "/admin/pause")


def run():
    print("\nStarting simulator...")
    return request("POST", "/admin/run")


def step(count=1):
    result = None

    for i in range(count):
        result = request("POST", "/admin/step")

        if result:
            print(
                f"Step {i + 1}/{count}: "
                f"tick={result.get('tick')} "
                f"time={result.get('sim_time')}"
            )

    return result


def create_event(
    event_type: str,
    start_tick: int,
    duration_ticks: int,
    parameters=None,
):
    payload = {
        "type": event_type,
        "start_tick": start_tick,
        "duration_ticks": duration_ticks,
        "parameters": parameters or {},
    }

    print("\nCreating event:")
    print(payload)

    return request(
        "POST",
        "/admin/events",
        json=payload,
    )


def current_tick():
    instance = get_instance()
    return instance["tick"]


def print_metrics():
    metrics = get_metrics()

    print("\n========== METRICS ==========")

    for key, value in metrics.items():
        print(f"{key}: {value}")

    print("=============================\n")

    return metrics