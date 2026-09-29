#!/usr/bin/env python3

import argparse
import time
import requests


SIMULATOR = "http://localhost:8000"


FAULT_PARAMETERS = {
    "latency": {
        "delay_ms": 1000,
    },
    "unavailable": {},
    "error_rate": {
        "rate": 0.50,
    },
    "stale_data": {},
    "stream_disconnect": {},
}


def inject_fault(fault_type, duration):
    payload = {
        "type": fault_type,
        "duration_seconds": duration,
        "parameters": FAULT_PARAMETERS[fault_type],
    }

    r = requests.post(
        f"{SIMULATOR}/admin/faults",
        json=payload,
        timeout=10,
    )

    print("Inject:", r.status_code)
    print(r.text)

    r.raise_for_status()


def test_state():
    start = time.perf_counter()

    try:
        r = requests.get(
            f"{SIMULATOR}/v1/stations",
            timeout=10,
        )

        elapsed = (
            time.perf_counter() - start
        ) * 1000

        print()
        print("Status:", r.status_code)
        print(f"Latency: {elapsed:.1f} ms")
        print(
            "X-Simulator-Stale:",
            r.headers.get("X-Simulator-Stale"),
        )

        print("Body:")
        print(r.text[:1000])

    except Exception as exc:
        elapsed = (
            time.perf_counter() - start
        ) * 1000

        print(f"Failed after {elapsed:.1f} ms")
        print(exc)


def test_stream():
    try:
        r = requests.get(
            f"{SIMULATOR}/v1/stream",
            stream=True,
            timeout=5,
        )

        print("Stream status:", r.status_code)
        print(r.text[:500])

    except Exception as exc:
        print("Stream failed:")
        print(exc)


def clear_faults():
    r = requests.post(
        f"{SIMULATOR}/admin/faults/clear",
        timeout=10,
    )

    print("Clear:", r.status_code, r.text)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "fault",
        choices=FAULT_PARAMETERS.keys(),
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=30,
    )

    args = parser.parse_args()

    inject_fault(
        args.fault,
        args.duration,
    )

    if args.fault == "stream_disconnect":
        test_stream()
    else:
        test_state()

    print(
        "\nLeave the fault active and inspect "
        "your PLATFORM dashboard now."
    )

    input("\nPress Enter to clear fault...")

    clear_faults()


if __name__ == "__main__":
    main()