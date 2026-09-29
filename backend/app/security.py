import hmac

from fastapi import Header, HTTPException

from .config import get_settings


def require_operator(x_operator_key: str | None = Header(default=None)) -> None:
    """Sensitive operator actions (approve, mode change, chaos) need X-Operator-Key (brief §18)."""
    expected = get_settings().operator_key
    if not x_operator_key or not hmac.compare_digest(x_operator_key, expected):
        raise HTTPException(status_code=401, detail={"code": "OPERATOR_KEY_REQUIRED",
                                                     "message": "Valid X-Operator-Key header required"})
