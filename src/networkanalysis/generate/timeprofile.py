"""Deterministic diurnal + weekly load shape used to modulate demand across the run."""

from __future__ import annotations

import numpy as np
import pandas as pd

# 24 hourly multipliers (local time), mobile-network-typical: morning ramp, midday
# plateau, evening busy hour ~20:00-22:00, overnight trough.
_HOURLY = np.array(
    [
        0.34, 0.26, 0.21, 0.19, 0.20, 0.28,  # 00-05
        0.45, 0.66, 0.82, 0.90, 0.93, 0.95,  # 06-11
        0.97, 0.95, 0.93, 0.94, 0.97, 1.00,  # 12-17
        1.06, 1.12, 1.15, 1.08, 0.86, 0.55,  # 18-23
    ]
)

# Monday..Sunday - weekends slightly lower daytime, flatter
_DOW = np.array([1.00, 1.01, 1.02, 1.03, 1.05, 0.92, 0.85])


def build_time_index(start_date, n_bins: int, bin_seconds: int) -> pd.DatetimeIndex:
    start = pd.Timestamp(start_date)
    return pd.date_range(start=start, periods=n_bins, freq=pd.Timedelta(seconds=bin_seconds))


def load_shape(ts_index: pd.DatetimeIndex) -> np.ndarray:
    """Multiplicative demand shape in roughly [0.2, 1.2], one value per timestamp."""
    hour = ts_index.hour.to_numpy()
    frac = ts_index.minute.to_numpy() / 60.0
    # smooth interpolation between hourly points
    nxt = (hour + 1) % 24
    hourly = _HOURLY[hour] * (1 - frac) + _HOURLY[nxt] * frac
    dow = _DOW[ts_index.dayofweek.to_numpy()]
    return hourly * dow
