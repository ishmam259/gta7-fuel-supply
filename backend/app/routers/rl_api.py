"""RL vs deterministic comparison for the console (read-only; saved results, no simulator calls)."""
from functools import lru_cache

from fastapi import APIRouter

router = APIRouter(prefix="/api/rl")


@lru_cache(maxsize=1)
def _summary() -> dict:
    try:
        from app.intel.rl import summary
        return summary()
    except Exception as exc:  # never break the console
        return {"available": False, "error": repr(exc)}


@router.get("/summary")
def rl_summary() -> dict:
    return _summary()
