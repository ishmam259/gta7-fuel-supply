from common import (
    reset,
    pause,
    step,
    create_event,
    current_tick,
    print_metrics,
    get_stations,
)

reset()
pause()

tick = current_tick()

print(f"\nCurrent tick: {tick}")

create_event(
    event_type="demand_spike",
    start_tick=tick + 1,
    duration_ticks=16,
    parameters={
        "station_ids": ["station-mirpur"],
        "multiplier": 2.0,
    },
)

print("\nBEFORE CRISIS")
print_metrics()

print("\nAdvancing into crisis...")
step(1)

print("\nStation state:")
for station in get_stations():
    if station["id"] == "station-mirpur":
        print(station)

print("\nRunning 16 crisis ticks...")
step(16)

print("\nAFTER CRISIS")
print_metrics()