"""Correlation & driver analysis -> correlation_edge.

Spearman + partial correlation between KPI pairs (market-wide and for each priority site),
plus lead/lag cross-correlation to spot precursors (e.g. SevOne queue buildup preceding a
YouTube QoE drop), plus a per-site layer-driver split (transport vs radio variance share).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PAIRS = [
    ("sevone_queue_depth", "tcp_client_rtt_ms"),
    ("twamp_loss_pct", "retrans_pct"),
    ("twamp_loss_pct", "vonr_mos"),
    ("path_delay_ms", "tcp_client_rtt_ms"),
    ("sevone_util_pct", "dl_throughput_mbps"),
    ("prb_util_p95", "dl_throughput_mbps"),
    ("rsrq_p50", "vonr_mos"),
    ("dl_throughput_mbps", "youtube_qoe_mos"),
    ("tcp_client_rtt_ms", "youtube_qoe_mos"),
    ("sevone_queue_depth", "youtube_qoe_mos"),
]
RADIO = ["rsrp_p50", "rsrq_p50", "prb_util_p95"]
TRANSPORT = ["path_delay_ms", "path_jitter_ms", "path_loss_pct", "twamp_loss_pct",
             "sevone_queue_depth", "sevone_util_pct"]


def _spearman(a: pd.Series, b: pd.Series) -> float:
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 12 or d.iloc[:, 0].nunique() < 3 or d.iloc[:, 1].nunique() < 3:
        return np.nan
    return float(d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank()))


def _partial(df: pd.DataFrame, a: str, b: str, controls: list[str]) -> float:
    cols = [c for c in [a, b, *controls] if c in df.columns]
    d = df[cols].dropna()
    if len(d) < 30:
        return np.nan
    from numpy.linalg import pinv

    r = d.rank()
    C = np.corrcoef(r.values.T)
    try:
        P = -pinv(C)
        ia, ib = 0, 1
        denom = np.sqrt(P[ia, ia] * P[ib, ib])
        return float(P[ia, ib] / denom) if denom else np.nan
    except Exception:
        return np.nan


def _best_lag(a: pd.Series, b: pd.Series, max_lag: int = 6) -> tuple[int, float]:
    d = pd.concat([a, b], axis=1).dropna()
    if len(d) < 3 * max_lag:
        return 0, np.nan
    x, y = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    best_l, best_c = 0, 0.0
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            c = np.corrcoef(x[:lag], y[-lag:])[0, 1]
        elif lag > 0:
            c = np.corrcoef(x[lag:], y[:-lag])[0, 1]
        else:
            c = np.corrcoef(x, y)[0, 1]
        if abs(c) > abs(best_c):
            best_l, best_c = lag, c
    return best_l * 60, float(best_c)  # minutes (hourly grid)


def compute_correlations(feat: pd.DataFrame, scorecard: pd.DataFrame, top_sites: int = 60) -> pd.DataFrame:
    rows = []

    def emit(scope, scope_id, df):
        for a, b in PAIRS:
            if a not in df.columns or b not in df.columns:
                continue
            sp = _spearman(df[a], df[b])
            if np.isnan(sp):
                continue
            controls = [c for c in RADIO + TRANSPORT if c not in (a, b)][:4]
            pa = _partial(df, a, b, controls)
            lag_min, lag_c = _best_lag(df[a], df[b])
            rows.append({
                "scope": scope, "scope_id": scope_id, "metric_a": a, "metric_b": b,
                "spearman": round(sp, 4), "partial": None if np.isnan(pa) else round(pa, 4),
                "best_lag_min": int(lag_min), "lag_corr": None if np.isnan(lag_c) else round(lag_c, 4),
            })

    emit("market", "ALL", feat)

    priority = scorecard.sort_values("impact_score", ascending=False).head(top_sites).site_id.tolist()
    for site in priority:
        emit("site", site, feat[feat.site_id == site].sort_values("ts_hour"))

    return pd.DataFrame(rows)


def layer_driver_split(feat: pd.DataFrame, scorecard: pd.DataFrame, target: str = "youtube_qoe_mos",
                       top_sites: int = 120) -> pd.DataFrame:
    """Per site: share of target-KPI variance explained by transport vs radio blocks (via
    simple R^2 of block-only OLS on ranks)."""
    from numpy.linalg import lstsq

    out = []
    priority = scorecard.sort_values("impact_score", ascending=False).head(top_sites).site_id.tolist()
    for site in priority:
        d = feat[feat.site_id == site]
        if len(d) < 40 or target not in d:
            continue
        y = d[target].rank().to_numpy()
        y = y - y.mean()

        def r2(block):
            cols = [c for c in block if c in d.columns]
            X = d[cols].rank().to_numpy()
            X = np.column_stack([np.ones(len(X)), X - X.mean(0)])
            beta, *_ = lstsq(X, y, rcond=None)
            resid = y - X @ beta
            ss = (y**2).sum()
            return float(1 - (resid**2).sum() / ss) if ss else 0.0

        rt, rr = max(r2(TRANSPORT), 0), max(r2(RADIO), 0)
        tot = rt + rr + 1e-9
        out.append({
            "site_id": site, "target": target,
            "transport_share": round(rt / tot, 3), "radio_share": round(rr / tot, 3),
            "r2_transport": round(rt, 3), "r2_radio": round(rr, 3),
        })
    return pd.DataFrame(out)
