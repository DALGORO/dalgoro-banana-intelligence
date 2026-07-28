from __future__ import annotations
from pathlib import Path
import json
from typing import Any, Dict
from app.core.config import settings

_FLAGS_PATH = Path(__file__).resolve().parents[2] / "app" / "storage" / "config" / "feature_flags.json"
_DEFAULTS = {"payment_required": bool(getattr(settings, "PAYMENT_REQUIRED", False))}

def _ensure_dir():
    _FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_flags() -> Dict[str, Any]:
    try:
        if _FLAGS_PATH.exists():
            file_flags = json.loads(_FLAGS_PATH.read_text("utf-8"))
            return {**_DEFAULTS, **file_flags}
    except Exception:
        pass
    return dict(_DEFAULTS)

def save_flags(flags: Dict[str, Any]) -> None:
    _ensure_dir()
    _FLAGS_PATH.write_text(json.dumps(flags, ensure_ascii=False, indent=2), encoding="utf-8")

def get_payment_required() -> bool:
    return bool(load_flags().get("payment_required", False))

def set_payment_required(value: bool) -> Dict[str, Any]:
    flags = load_flags()
    flags["payment_required"] = bool(value)
    save_flags(flags)
    return flags
