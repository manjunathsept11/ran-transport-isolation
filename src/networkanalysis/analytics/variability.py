"""Variability analysis -> variability_site.

Per site + KPI: coefficient of variation, IQR, busy-hour vs off-peak spread, a
within-day / day-to-day variance decomposition, a week-over-week PSI drift check, and a
stability rank that surfaces sites whose *mean* is acceptable but whose *variance* is high
(the fingerprint of intermittent transport faults such as microwave fade).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

METRICS = ["tcp_client_rtt_ms", "dl_throughput_mbps", "vonr_mos", "youtube_qoe_mos", "twamp_loss_pct"]
BUSY = {18, 19, 20, 21, 22}


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    e = expected[~np.isnan(expected)]
    a = actual[~np.isnan(actual)]
    if len(e) < 20 or len(a) < 20:
        return np.nan
    qs = np.quantile(e, np.linspace(0, 1, bins + 1))
    qs[0], qs[-1] = -np.inf, np.inf
    e_hist = np.histogram(e, qs)[0] / len(e) + 1e-6
    a_hist = np.histogram(a, qs)[0] / len(a) + 1e-6
    return float(np.sum((a_hist - e_hist) * np.log(a_hist / e_hist)))


def compute_variability(feat: pd.DataFrame, primary: str = "tcp_client_rtt_ms") -> pd.DataFrame:
    feat = feat.copy()
    feat["date"] = feat.ts_hour.dt.date
    feat["hour"] = feat.ts_hour.dt.hour
    rows = []
    mid = feat.ts_hour.min() + (feat.ts_hour.max() - feat.ts_hour.min()) / 2

    for site, g in feat.groupby("site_id"):
        y = g[primary].astype(float)
        if y.notna().sum() < 40:
            continue
        mean = y.mean()
        cv = float(y.std(ddof=0) / mean) if mean else np.nan
        iqr = float(y.quantile(0.75) - y.quantile(0.25))
        busy = y[g.hour.isin(BUSY)].mean()
        off = y[~g.hour.isin(BUSY)].mean()
        ratio = float(busy / off) if off else np.nan

        daily_mean = g.groupby("date")[primary].mean()
        within = float(g.groupby("date")[primary].var(ddof=0).mean())
        between = float(daily_mean.var(ddof=0))

        first = y[g.ts_hour < mid].to_numpy()
        second = y[g.ts_hour >= mid].to_numpy()
        psi = _psi(first, second)

        rows.append({
            "site_id": site, "metric": primary,
            "cv": round(cv, 4) if not np.isnan(cv) else None,
            "iqr": round(iqr, 4), "busy_offpeak_ratio": round(ratio, 4) if not np.isnan(ratio) else None,
            "within_day_var": round(within, 4), "day_to_day_var": round(between, 4),
            "mean": round(float(mean), 4),
            "wow_psi": round(psi, 4) if not np.isnan(psi) else None,
            "wow_shift": int((psi or 0) > 0.2),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # stability rank: high variance relative to peers with a *similar mean*
    df["mean_band"] = pd.qcut(df["mean"].rank(method="first"), 5, labels=False, duplicates="drop")
    df["_instab"] = df.groupby("mean_band")["cv"].transform(lambda s: s.rank(pct=True))
    df = df.sort_values("_instab", ascending=False)
    df["stability_rank"] = np.arange(1, len(df) + 1)
    df["instability_flag"] = ((df["_instab"] > 0.9) & (df["cv"] > df["cv"].median() * 1.4)).astype(int)
    return df.drop(columns=["mean_band", "_instab", "mean"])


def variance_components_market(feat: pd.DataFrame, metric: str = "tcp_client_rtt_ms") -> dict:
    """Crude ANOVA-style variance share: site, hour-of-day, day, residual."""
    d = feat[["site_id", "ts_hour", metric]].dropna().copy()
    if len(d) < 500:
        return {}
    d["hour"] = d.ts_hour.dt.hour
    d["date"] = d.ts_hour.dt.date
    grand = d[metric].mean()
    total = float(((d[metric] - grand) ** 2).sum()) or 1.0

    def ss(col):
        m = d.groupby(col)[metric].transform("mean")
        return float(((m - grand) ** 2).sum())

    comp = {"site": ss("site_id"), "hour_of_day": ss("hour"), "day": ss("date")}
    comp["residual"] = max(total - sum(comp.values()), 0.0)
    tot = sum(comp.values()) or 1.0
    return {k: round(v / tot, 4) for k, v in comp.items()}
