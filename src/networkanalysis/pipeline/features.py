"""The unified site feature table that every analytics module consumes.

Reads ``agg_site_hourly`` + ``dim_site``, adds robust deviations from each site's own
rolling baseline and from its morphology peer group, and tags the diurnal busy hour.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from networkanalysis.db.database import connect

# the five headline KPIs the module ranks on (brief: TCP RTT, TCP fail %, Ookla
# throughput, VoNR MOS, YouTube QoE). direction = +1 if "higher is worse".
HEADLINE_KPIS = {
    "tcp_client_rtt_ms": +1,
    "tcp_fail_pct": +1,
    "dl_throughput_mbps": -1,
    "vonr_mos": -1,
    "youtube_qoe_mos": -1,
}

# every KPI we baseline / anomaly-check, with direction
KPI_DIRECTION = {
    **HEADLINE_KPIS,
    "tcp_server_rtt_ms": +1,   # internet-side control (should stay flat during access/transport faults)
    "retrans_pct": +1,
    "loaded_latency_ms": +1,
    "rebuffer_ratio": +1,
    "rsrp_p50": -1,
    "rsrq_p50": -1,
    "prb_util_p95": +1,
    "path_delay_ms": +1,
    "path_jitter_ms": +1,
    "path_loss_pct": +1,
    "twamp_rtt_ms": +1,
    "twamp_jitter_ms": +1,
    "twamp_loss_pct": +1,
    "sevone_util_pct": +1,
    "sevone_queue_depth": +1,
    "sevone_discards": +1,
    "sevone_crc": +1,
    "availability": -1,
}

BUSY_HOURS = {18, 19, 20, 21, 22}


def load_site_hourly(db_path=None) -> pd.DataFrame:
    con = connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM agg_site_hourly", con)
        dim = pd.read_sql_query(
            "SELECT site_id, region, morphology, backhaul_type FROM dim_site", con
        )
    finally:
        con.close()
    df = df.merge(dim, on="site_id", how="left")
    df["ts_hour"] = pd.to_datetime(df["ts_hour"])
    return df.sort_values(["site_id", "ts_hour"]).reset_index(drop=True)


def _robust_z(x: pd.Series, center: pd.Series, scale: pd.Series) -> pd.Series:
    return (x - center) / scale.replace(0, np.nan).fillna(scale.median() or 1.0)


def build_site_feature_table(db_path=None, baseline_window: int = 48) -> pd.DataFrame:
    df = load_site_hourly(db_path)
    df["hour"] = df["ts_hour"].dt.hour
    df["dow"] = df["ts_hour"].dt.dayofweek
    df["is_busy_hour"] = df["hour"].isin(BUSY_HOURS).astype(int)

    metrics = [m for m in KPI_DIRECTION if m in df.columns]

    # ---- own baseline: TRAILING rolling median for centre and a trailing rolling
    #      inter-decile range for scale. Both use only past data (shift(1)) so an ongoing
    #      incident does not inflate the site's own baseline / hide its own anomaly.
    g = df.groupby("site_id", group_keys=False)
    w = baseline_window
    for m in metrics:
        med = g[m].transform(lambda s: s.shift(1).rolling(w, min_periods=12).median())
        q10 = g[m].transform(lambda s: s.shift(1).rolling(w, min_periods=12).quantile(0.10))
        q90 = g[m].transform(lambda s: s.shift(1).rolling(w, min_periods=12).quantile(0.90))
        med = med.fillna(g[m].transform("median"))
        scale = ((q90 - q10) / 2.563).abs()
        scale = scale.replace(0, np.nan).fillna(
            (g[m].transform(lambda s: s.quantile(0.9) - s.quantile(0.1)) / 2.563).abs()
        ).fillna(g[m].transform(lambda s: s.std(ddof=0))).replace(0, np.nan).fillna(1.0)
        df[f"{m}__z"] = _robust_z(df[m], med, scale).clip(-25, 25)
        df[f"{m}__base"] = med

    # ---- peer-group baseline (same morphology + similar load, same hour) ----
    df["load_band"] = pd.qcut(df.groupby("morphology")["sessions"].rank(pct=True), 3,
                              labels=["lo", "mid", "hi"], duplicates="drop")
    peer_keys = ["morphology", "load_band", "hour"]
    for m in metrics:
        peer_med = df.groupby(peer_keys)[m].transform("median")
        peer_mad = (1.4826 * df.groupby(peer_keys)[m].transform(
            lambda s: np.nanmedian(np.abs(s - np.nanmedian(s))))).replace(0, np.nan)
        peer_mad = peer_mad.fillna(df[m].std(ddof=0) or 1.0)
        df[f"{m}__peer_z"] = _robust_z(df[m], peer_med, peer_mad).clip(-25, 25)

    return df
