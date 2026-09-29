from common import (
    reset,
    pause,
    step,
    create_event,
    current_tick,
    request,
)

reset()
pause()

tick = current_tick()

print("\nSupply arrivals BEFORE:")
arrivals = request("GET", "/v1/supply-arrivals")

for arrival in arrivals[:10]:
    print(arrival)

create_event(
    event_type="shipment_delay",
    start_tick=tick + 1,
    duration_ticks=1,
    parameters={
        "delay_ticks": 8,
        "depot_ids": ["depot-gazipur"],
        "fuel_types": ["DIESEL"],
    },
)

step(1)

print("\nSupply arrivals AFTER:")
arrivals = request("GET", "/v1/supply-arrivals")

for arrival in arrivals[:10]:
    print(arrival)