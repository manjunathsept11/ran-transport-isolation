"""Build hourly serving rollups (agg_site_hourly, agg_link_hourly) from the 5-min parquet.

agg_site_hourly is the unified KPI panel the dashboard, analytics and report read: radio +
session + app KPIs for the site, plus the transport health of its path (TWAMP / SevOne /
link state rolled along the 3 hops).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from networkanalysis.topology.generate import Topology

_SITE_AGG = {
    "rsrp_dbm": "median", "rsrq_db": "median", "prb_util_pct": lambda s: s.quantile(0.95),
    "tcp_client_rtt_ms": "mean", "tcp_server_rtt_ms": "mean", "tcp_fail_pct": "mean",
    "retrans_pct": "mean", "vonr_mos": "mean", "dl_throughput_mbps": "mean",
    "ul_throughput_mbps": "mean", "loaded_latency_ms": "mean", "youtube_qoe_mos": "mean",
    "rebuffer_ratio": "mean", "path_delay_ms": "mean", "path_jitter_ms": "mean",
    "path_loss_pct": "mean", "sessions": "sum", "users": "mean", "availability": "min",
}
_LINK_AGG = {
    "util_pct": "mean", "queue_occ": "mean", "delay_ms": "mean", "jitter_ms": "mean",
    "loss_pct": "mean", "discards_pps": "mean", "crc_rate": "mean", "availability": "min",
}


def _hourly(df: pd.DataFrame, key: str, aggs: dict) -> pd.DataFrame:
    df = df.copy()
    df["ts_hour"] = pd.to_datetime(df["ts"]).dt.floor("h")
    return df.groupby([key, "ts_hour"]).agg(aggs).reset_index()


def build_rollups(topo: Topology, site_bin_files: list[str], link_bin_files: list[str],
                  twamp_files: list[str], sevone_files: list[str], progress=None) -> dict[str, pd.DataFrame]:
    import pyarrow.parquet as pq

    groups = [
        ("site_bin", site_bin_files, "site_id", _SITE_AGG),
        ("link_bin", link_bin_files, "link_id", _LINK_AGG),
        ("twamp", twamp_files, "link_id", {"rtt_ms": "mean", "jitter_ms": "mean", "frame_loss_pct": "mean"}),
        ("sevone", sevone_files, "link_id",
         {"in_util_pct": "mean", "queue_depth": "mean", "discards": "mean", "crc_errors": "mean"}),
    ]
    total = sum(len(g[1]) for g in groups) or 1
    done = 0
    parts: dict[str, list] = {}
    for name, files, key, aggs in groups:
        acc = []
        for f in files:
            acc.append(_hourly(pq.read_table(f).to_pandas(), key, aggs))
            done += 1
            if progress:
                progress(f"aggregating {name} ({done}/{total} files)", done / total)
        parts[name] = acc

    site_parts, link_parts, twamp_parts, sev_parts = (
        parts["site_bin"], parts["link_bin"], parts["twamp"], parts["sevone"]
    )

    site_h = pd.concat(site_parts, ignore_index=True)
    link_h = pd.concat(link_parts, ignore_index=True)
    twamp_h = pd.concat(twamp_parts, ignore_index=True).rename(
        columns={"rtt_ms": "twamp_rtt_ms", "jitter_ms": "twamp_jitter_ms", "frame_loss_pct": "twamp_loss_pct"}
    )
    sev_h = pd.concat(sev_parts, ignore_index=True).rename(
        columns={"in_util_pct": "sevone_util_pct", "queue_depth": "sevone_queue_depth",
                 "discards": "sevone_discards", "crc_errors": "sevone_crc"}
    )

    site_h = site_h.rename(columns={"prb_util_pct": "prb_util_p95", "rsrp_dbm": "rsrp_p50", "rsrq_db": "rsrq_p50"})

    # ---- transport path -> site ----
    path = topo.path_links[["site_id", "link_id"]]
    tp = (
        link_h.merge(twamp_h, on=["link_id", "ts_hour"], how="left")
        .merge(sev_h, on=["link_id", "ts_hour"], how="left")
    )
    merged = path.merge(tp, on="link_id", how="inner")
    grp = merged.groupby(["site_id", "ts_hour"])
    path_roll = grp.agg(
        path_delay_ms_lk=("delay_ms", "sum"),
        path_jitter_ms_lk=("jitter_ms", lambda s: float(np.sqrt(np.nansum(np.square(s))))),
        path_loss_pct_lk=("loss_pct", lambda s: float((1 - np.prod(1 - np.clip(s.fillna(0), 0, 100) / 100)) * 100)),
        twamp_rtt_ms=("twamp_rtt_ms", "max"),
        twamp_jitter_ms=("twamp_jitter_ms", "max"),
        twamp_loss_pct=("twamp_loss_pct", "max"),
        sevone_util_pct=("sevone_util_pct", "max"),
        sevone_queue_depth=("sevone_queue_depth", "max"),
        sevone_discards=("sevone_discards", "max"),
        sevone_crc=("sevone_crc", "max"),
    ).reset_index()

    site_h = site_h.merge(path_roll, on=["site_id", "ts_hour"], how="left")
    site_h["path_delay_ms"] = site_h["path_delay_ms_lk"].fillna(site_h["path_delay_ms"])
    site_h["path_jitter_ms"] = site_h["path_jitter_ms_lk"].fillna(site_h["path_jitter_ms"])
    site_h["path_loss_pct"] = site_h["path_loss_pct_lk"].fillna(site_h["path_loss_pct"])
    site_h = site_h.drop(columns=["path_delay_ms_lk", "path_jitter_ms_lk", "path_loss_pct_lk"])

    site_dim = topo.sites.set_index("site_id")[["region", "morphology"]]
    site_h = site_h.merge(site_dim, left_on="site_id", right_index=True, how="left")

    for c in ("ts_hour",):
        site_h[c] = site_h[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        link_h[c] = link_h[c].dt.strftime("%Y-%m-%d %H:%M:%S")

    # final column order for agg_site_hourly
    site_cols = [
        "ts_hour", "site_id", "rsrp_p50", "rsrq_p50", "prb_util_p95",
        "tcp_client_rtt_ms", "tcp_server_rtt_ms", "tcp_fail_pct", "retrans_pct", "vonr_mos",
        "dl_throughput_mbps", "ul_throughput_mbps", "loaded_latency_ms", "youtube_qoe_mos",
        "rebuffer_ratio", "path_delay_ms", "path_jitter_ms", "path_loss_pct",
        "twamp_rtt_ms", "twamp_jitter_ms", "twamp_loss_pct",
        "sevone_util_pct", "sevone_queue_depth", "sevone_discards", "sevone_crc",
        "sessions", "users", "availability",
    ]
    for c in site_cols:
        if c not in site_h.columns:
            site_h[c] = np.nan
    return {
        "agg_site_hourly": site_h[site_cols].round(4),
        "agg_link_hourly": link_h[
            ["ts_hour", "link_id", "util_pct", "queue_occ", "delay_ms", "jitter_ms",
             "loss_pct", "discards_pps", "crc_rate", "availability"]
        ].round(4),
    }
