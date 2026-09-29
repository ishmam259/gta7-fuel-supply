from common import (
    reset,
    pause,
    step,
    create_event,
    current_tick,
    get_routes,
    print_metrics,
)

reset()
pause()

tick = current_tick()
routes = get_routes()

mirpur_routes = [
    route
    for route in routes
    if route["destination_station_id"] == "station-mirpur"
]

print("\nMirpur routes:")

for route in mirpur_routes:
    print(route)

if not mirpur_routes:
    raise RuntimeError("No route to station-mirpur found")

route_to_disrupt = mirpur_routes[0]["id"]

#
# CRISIS 1
# Demand doubles at Mirpur
#

create_event(
    "demand_spike",
    tick + 1,
    24,
    {
        "station_ids": ["station-mirpur"],
        "multiplier": 2.0,
    },
)

#
# CRISIS 2
# Primary route unavailable
#

create_event(
    "route_disruption",
    tick + 4,
    12,
    {
        "route_ids": [route_to_disrupt],
    },
)

#
# CRISIS 3
# Diesel resupply delayed
#

create_event(
    "shipment_delay",
    tick + 2,
    1,
    {
        "delay_ticks": 8,
        "depot_ids": ["depot-gazipur"],
        "fuel_types": ["DIESEL"],
    },
)

print("\n================================")
print("COMBINED CRISIS CREATED")
print("================================")

print(f"Demand spike starts: {tick + 1}")
print(f"Shipment delay:      {tick + 2}")
print(f"Route disruption:    {tick + 4}")
print(f"Route:               {route_to_disrupt}")

print("\nBaseline metrics:")
print_metrics()

print("\nEntering crisis...")
step(4)

print("\nMetrics during crisis:")
print_metrics()

print(
    "\nSimulator is now paused during the crisis.\n"
    "Open the platform dashboard and inspect alerts/recommendations."
)