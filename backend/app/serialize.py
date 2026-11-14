"""JSON helpers shared by the tools, the trace and the agent loop."""
from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import ValidationError


def json_safe(value: Any) -> Any:
    """Plain JSON types only. `inf` becomes "infinite"; NaN is left alone so a stray one fails loudly."""
    if isinstance(value, float):
        return "infinite" if math.isinf(value) else round(value, 2)
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def strict_json(value):
    """JSON-safe for browsers: JSON.parse rejects Infinity and NaN, so they become strings."""
    if isinstance(value, float) and not math.isfinite(value):
        return "nan" if math.isnan(value) else "infinite" if value > 0 else "-infinite"
    if isinstance(value, dict):
        return {k: strict_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json(v) for v in value]
    return value


def readable(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors())
