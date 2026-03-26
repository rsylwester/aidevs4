"""Programmatic anomaly checks for sensor data."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Sensor type → allowed measurement fields
SENSOR_FIELDS: dict[str, set[str]] = {
    "temperature": {"temperature_K"},
    "pressure": {"pressure_bar"},
    "water": {"water_level_meters"},
    "voltage": {"voltage_supply_v"},
    "humidity": {"humidity_percent"},
}

# Valid ranges for active sensor fields
VALID_RANGES: dict[str, tuple[float, float]] = {
    "temperature_K": (553.0, 873.0),
    "pressure_bar": (60.0, 160.0),
    "water_level_meters": (5.0, 15.0),
    "voltage_supply_v": (229.0, 231.0),
    "humidity_percent": (40.0, 80.0),
}

ALL_MEASUREMENT_FIELDS: set[str] = {
    "temperature_K",
    "pressure_bar",
    "water_level_meters",
    "voltage_supply_v",
    "humidity_percent",
}

# Timestamp window: ~2 years from now
_TWO_YEARS_S = 2 * 365 * 24 * 3600


@dataclass
class CheckResult:
    """Result of programmatic checks on a single sensor record."""

    file_id: str
    is_anomaly: bool
    reasons: list[str]
    operator_note: str


def _allowed_fields_for_sensor(sensor_type: str) -> set[str] | None:
    """Return union of allowed fields for a (possibly multi-type) sensor. None if unknown."""
    parts = [p.strip() for p in sensor_type.split("/")]
    allowed: set[str] = set()
    for part in parts:
        if part not in SENSOR_FIELDS:
            return None  # unknown sensor type
        allowed |= SENSOR_FIELDS[part]
    return allowed


def check_record(file_id: str, data: dict[str, Any]) -> CheckResult:
    """Run all programmatic checks on a sensor record."""
    reasons: list[str] = []
    sensor_type: str = str(data.get("sensor_type", ""))
    operator_note: str = str(data.get("operator_notes", ""))

    # 1. Timestamp validation
    ts = data.get("timestamp")
    if not _valid_timestamp(ts):
        reasons.append(f"invalid_timestamp={ts}")

    # 2. Unknown sensor type
    allowed = _allowed_fields_for_sensor(sensor_type)
    if allowed is None:
        reasons.append(f"unknown_sensor_type={sensor_type}")
        # Can't do field/range checks without known type
        return CheckResult(file_id=file_id, is_anomaly=True, reasons=reasons, operator_note=operator_note)

    # 3. Inactive fields must be 0
    inactive_fields = ALL_MEASUREMENT_FIELDS - allowed
    for field in inactive_fields:
        val = data.get(field, 0)
        if isinstance(val, (int, float)) and val != 0:
            reasons.append(f"inactive_field_nonzero={field}:{val}")

    # 4. Active fields in range
    for field in allowed:
        val = data.get(field)
        if val is None:
            reasons.append(f"missing_active_field={field}")
            continue
        if not isinstance(val, (int, float)):
            reasons.append(f"non_numeric_field={field}:{val}")
            continue
        lo, hi = VALID_RANGES[field]
        if val < lo or val > hi:
            reasons.append(f"out_of_range={field}:{val} (valid {lo}-{hi})")

    return CheckResult(
        file_id=file_id,
        is_anomaly=len(reasons) > 0,
        reasons=reasons,
        operator_note=operator_note,
    )


def _valid_timestamp(ts: Any) -> bool:
    """Check if timestamp is a valid unix timestamp within ~2 year window."""
    if not isinstance(ts, (int, float)):
        return False
    now = time.time()
    return (now - _TWO_YEARS_S) <= ts <= (now + _TWO_YEARS_S)
