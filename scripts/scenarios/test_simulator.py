from common import (
    reset,
    pause,
    step,
    print_metrics,
    get_instance,
)

reset()
pause()

print("\nInitial instance:")
print(get_instance())

print("\nAdvancing 5 ticks...")
step(5)

print_metrics()