from common import (
    reset,
    pause,
    step,
    create_event,
    current_tick,
    get_routes,
)

reset()
pause()

routes = get_routes()

print("\nAvailable routes:")

for route in routes:
    print(
        route["id"],
        route["source_depot_id"],
        "->",
        route["destination_station_id"],
        route["status"],
    )

target_route = routes[0]["id"]

print(f"\nDisrupting: {target_route}")

tick = current_tick()

create_event(
    event_type="route_disruption",
    start_tick=tick + 1,
    duration_ticks=12,
    parameters={
        "route_ids": [target_route],
    },
)

step(1)

print("\nDURING DISRUPTION")

for route in get_routes():
    if route["id"] == target_route:
        print(route)

step(12)

print("\nAFTER DISRUPTION")

for route in get_routes():
    if route["id"] == target_route:
        print(route)