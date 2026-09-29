from common import (
    reset,
    pause,
    step,
    create_event,
    current_tick,
    get_depots,
)

reset()
pause()

tick = current_tick()

create_event(
    event_type="depot_constraint",
    start_tick=tick + 1,
    duration_ticks=12,
    parameters={
        "depot_ids": ["depot-gazipur"],
    },
)

step(1)

print("\nDEPOTS DURING CRISIS")

for depot in get_depots():
    print(
        depot["id"],
        "status=",
        depot["status"],
    )

step(12)

print("\nDEPOTS AFTER CRISIS")

for depot in get_depots():
    print(
        depot["id"],
        "status=",
        depot["status"],
    )