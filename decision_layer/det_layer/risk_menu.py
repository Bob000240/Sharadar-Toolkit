"""
Deterministic risk-choice catalog and resolvers.

Per the option-2 design, the *definitions* of stop/target/timeline IDs live in
code (here); each strategy resolves the IDs its profile permits into concrete,
self-describing menu objects ({id, price, pct, ...}) that are written onto the
candidate packet. The agent may only pick an ID present in those menus.
"""

from __future__ import annotations
import math

# Timeline ID -> intended holding days.
TIMELINES: dict[str, int] = {
    "swing_20d": 20,
    "position_45d": 45,
    "position_60d": 60,
    "trend_90d": 90,
    "trend_120d": 120,
}

# Stop definitions: (kind, param, label).
#   kind="atr"   -> stop = entry - param * ATR
#   kind="pct"   -> stop = entry * (1 - param)
#   kind="level" -> stop = levels[param]  (e.g. a moving-average price)
_STOP_DEFS: dict[str, tuple[str, object, str]] = {
    "atr_2x": ("atr", 2.0, "2x ATR"),
    "atr_2_5x": ("atr", 2.5, "2.5x ATR"),
    "atr_3x": ("atr", 3.0, "3x ATR"),
    "pct_8": ("pct", 0.08, "8% fixed"),
    "pct_12": ("pct", 0.12, "12% fixed"),
    "pct_15": ("pct", 0.15, "15% fixed"),
    "sma_50": ("level", "sma_50", "below 50DMA"),
}

# Target definitions: (kind, param, label).
#   kind="pct" -> target = entry * (1 + param)
#   kind="rr"  -> target = entry + param * default_stop_distance  (reward/risk)
_TARGET_DEFS: dict[str, tuple[str, float, str]] = {
    "rr_1_5": ("rr", 1.5, "1.5R"),
    "rr_2": ("rr", 2.0, "2R"),
    "rr_3": ("rr", 3.0, "3R"),
    "pct_10": ("pct", 0.10, "10% target"),
    "pct_15": ("pct", 0.15, "15% target"),
    "pct_25": ("pct", 0.25, "25% target"),
}


def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def _r(x: float) -> float:
    return round(float(x), 4)


def resolve_stop(stop_id: str, entry: float, atr: float | None, levels: dict) -> dict | None:
    """Resolve a stop ID to a {id, price, pct, label} below entry, or None if invalid."""
    kind, param, label = _STOP_DEFS[stop_id]
    if kind == "atr":
        if not _finite(atr) or atr <= 0:
            return None
        price = entry - param * atr
    elif kind == "pct":
        price = entry * (1 - param)
    elif kind == "level":
        price = levels.get(param)
        if not _finite(price):
            return None
    else:
        return None
    # A long stop must be a valid level strictly below entry.
    if not _finite(price) or price <= 0 or price >= entry:
        return None
    return {"id": stop_id, "price": _r(price), "pct": _r(price / entry - 1), "label": label}


def resolve_target(
    target_id: str, entry: float, default_stop_distance: float | None
) -> dict | None:
    """Resolve a target ID to a {id, price, pct, rr, label} above entry, or None."""
    kind, param, label = _TARGET_DEFS[target_id]
    if kind == "rr":
        if not _finite(default_stop_distance) or default_stop_distance <= 0:
            return None
        price = entry + param * default_stop_distance
        rr = param
    elif kind == "pct":
        price = entry * (1 + param)
        rr = None
    else:
        return None
    if not _finite(price) or price <= entry:
        return None
    return {
        "id": target_id,
        "price": _r(price),
        "pct": _r(price / entry - 1),
        "rr": rr,
        "label": label,
    }


def _pick(menu: list[dict], default_id: str) -> dict | None:
    if not menu:
        return None
    return next((m for m in menu if m["id"] == default_id), menu[0])


def build_menus(
    entry: float,
    atr: float | None,
    levels: dict,
    allowed_stops: list[str],
    allowed_targets: list[str],
    allowed_timelines: list[str],
    default_stop_id: str,
    default_target_id: str,
    default_timeline_id: str,
) -> dict:
    """Resolve a profile's permitted IDs into concrete menus for one candidate.

    Returns {stop_menu, target_menu, timeline_menu, default_stop, default_target,
    default_timeline}. Targets are priced off the *default* stop distance so an
    'R'-multiple target is well defined. Menus may be empty if nothing resolves
    (e.g. ATR-only stops with no ATR) — the caller decides whether to drop the name.
    """
    if not _finite(entry) or entry <= 0:
        return {
            "stop_menu": [],
            "target_menu": [],
            "timeline_menu": [],
            "default_stop": None,
            "default_target": None,
            "default_timeline": None,
        }

    stop_menu = [s for s in (resolve_stop(i, entry, atr, levels) for i in allowed_stops) if s]
    default_stop = _pick(stop_menu, default_stop_id)
    stop_distance = (entry - default_stop["price"]) if default_stop else None

    target_menu = [
        t for t in (resolve_target(i, entry, stop_distance) for i in allowed_targets) if t
    ]
    default_target = _pick(target_menu, default_target_id)

    timeline_menu = [
        {"id": i, "days": TIMELINES[i]} for i in allowed_timelines if i in TIMELINES
    ]
    default_timeline = _pick(timeline_menu, default_timeline_id)

    return {
        "stop_menu": stop_menu,
        "target_menu": target_menu,
        "timeline_menu": timeline_menu,
        "default_stop": default_stop,
        "default_target": default_target,
        "default_timeline": default_timeline,
    }
