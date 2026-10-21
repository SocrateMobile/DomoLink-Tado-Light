"""Adaptive Preheat and Thermal Drop Analysis for DomoLink-Tado-Light."""
from __future__ import annotations

import logging
import math

_LOGGER = logging.getLogger(__name__)


def estimate_preheat_duration(
    target_temp: float | None,
    current_temp: float | None,
    heating_rate: float,
    max_duration_minutes: int = 120,
) -> int:
    """Calculate required preheat duration in minutes.

    Formula:
        delta_T = target_temp - current_temp
        duration_minutes = (delta_T / heating_rate) * 60
    """
    if target_temp is None or current_temp is None:
        return 0

    try:
        t_target = float(target_temp)
        t_current = float(current_temp)
        rate = float(heating_rate)
    except (ValueError, TypeError):
        return 0

    if t_target <= t_current:
        return 0

    effective_rate = max(rate, 0.2)
    delta_t = t_target - t_current

    duration = int(math.ceil((delta_t / effective_rate) * 60.0))
    return max(0, min(duration, max_duration_minutes))


def update_heating_rate(
    current_rate: float,
    temp_start: float,
    temp_end: float,
    duration_hours: float,
) -> float:
    """Update heating rate (°C/hour) using Exponential Moving Average (EMA).

    Formula:
        measured_rate = (temp_end - temp_start) / duration_hours
        new_rate = 0.8 * current_rate + 0.2 * measured_rate
    """
    if duration_hours < 0.2:  # Moins de 12 min
        return round(current_rate, 2)

    delta_temp = temp_end - temp_start
    if delta_temp <= 0.0:
        return round(current_rate, 2)

    measured_rate = delta_temp / duration_hours
    clamped_measured = max(0.5, min(measured_rate, 6.0))

    new_rate = (0.8 * current_rate) + (0.2 * clamped_measured)
    return round(new_rate, 2)


def detect_rapid_temperature_drop(
    temp_history: list[tuple[float, float]],
    threshold_drop: float = 0.5,
    max_seconds: float = 300.0,
) -> bool:
    """Detect rapid temperature drop indicative of an open window.

    temp_history is a list of (timestamp, temperature) tuples sorted by timestamp.
    Returns True if temperature dropped by at least threshold_drop within max_seconds.
    """
    if not temp_history or len(temp_history) < 2:
        return False

    latest_time, latest_temp = temp_history[-1]

    for ts, temp in reversed(temp_history[:-1]):
        time_diff = latest_time - ts
        if time_diff > max_seconds:
            break
        drop = temp - latest_temp
        if drop >= threshold_drop:
            return True

    return False
