"""Temperature unit conversion."""

from __future__ import annotations

VALID_UNITS = ("F", "C")


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def normalize_unit(unit: str) -> str:
    u = (unit or "").strip().upper().replace("°", "")
    if u in ("F", "FAHRENHEIT"):
        return "F"
    if u in ("C", "CELSIUS"):
        return "C"
    raise ValueError(f"Unknown temperature unit: {unit!r}")


def to_f(value: float, unit: str) -> float:
    return value if normalize_unit(unit) == "F" else c_to_f(value)


def spread_to_f(spread: float, unit: str) -> float:
    """Convert a temperature *difference* (e.g. a standard deviation). No +32 offset."""
    return spread if normalize_unit(unit) == "F" else spread * 9.0 / 5.0
