"""Anomaly detection -> anomaly_event + incident_detected.

Univariate: STL residual + robust (MAD) thresholding per site/link KPI series.
Multivariate: Isolation Forest + PCA reconstruction error on the per-site-hour feature
vector. Changepoints via ruptures/PELT bound the event windows. Anomalies are then
clustered by time + transport topology into candidate incidents and matched to
``dim_incident``.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from networkanalysis.analytics.groundtruth import load_incidents
from networkanalysis.db.database import connect
from networkanalysis.pipeline.features import KPI_DIRECTION

UNIVAR_KPIS = ["tcp_client_rtt_ms", "tcp_fail_pct", "dl_throughput_mbps", "vonr_mos",
               "youtube_qoe_mos", "twamp_loss_pct", "sevone_queue_depth", "path_loss_pct"]
MULTIVAR_FEATURES = [f"{k}__z" for k in [
    "tcp_client_rtt_ms", "tcp_server_rtt_ms", "tcp_fail_pct", "retrans_pct",
    "dl_throughput_mbps", "vonr_mos", "youtube_qoe_mos", "rsrp_p50", "rsrq_p50",
    "prb_util_p95", "path_delay_ms", "path_loss_pct", "twamp_loss_pct",
    "sevone_queue_depth", "sevone_util_pct", "sevone_crc",
]]


def _stl_resid(y: pd.Series, period: int = 24) -> pd.Series:
    from statsmodels.tsa.seasonal import STL

    y = y.astype(float).interpolate(limit_direction="both")
    if len(y) < 2 * period + 2 or y.nunique() < 4:
        return y - y.median()
    try:
        res = STL(y, period=period, robust=True).fit()
        return res.resid
    except Exception:
        return y - y.rolling(period, min_periods=1, center=True).median()


def _events_from_mask(ts: pd.Series, mask: np.ndarray, sev: np.ndarray, direction: int,
                      entity_type: str, entity_id: str, metric: str, method: str,
                      min_len: int = 2) -> list[dict]:
    out = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        if j - i >= min_len:
            seg = slice(i, j)
            k = i + int(np.argmax(sev[seg]))
            out.append({
                "entity_type": entity_type, "entity_id": entity_id, "metric": metric,
                "start_ts": str(ts.iloc[i]), "end_ts": str(ts.iloc[j - 1]),
                "peak_ts": str(ts.iloc[k]), "severity": round(float(np.nanmax(sev[seg])), 3),
                "method": method, "direction": direction,
            })
        i = j
    return out


def univariate_anomalies(feat: pd.DataFrame, max_sites: int = 400,
                         scorecard: pd.DataFrame | None = None) -> pd.DataFrame:
    sites = feat.site_id.unique()
    if scorecard is not None and len(sites) > max_sites:
        sites = scorecard.sort_values("impact_score", ascending=False).head(max_sites).site_id.tolist()
    rows: list[dict] = []
    for site in sites:
        g = feat[feat.site_id == site].sort_values("ts_hour")
        if len(g) < 30:
            continue
        for kpi in UNIVAR_KPIS:
            if kpi not in g:
                continue
            direction = KPI_DIRECTION.get(kpi, 1)
            resid = _stl_resid(g[kpi], period=24).to_numpy()
            mad = 1.4826 * np.nanmedian(np.abs(resid - np.nanmedian(resid))) or (np.nanstd(resid) or 1.0)
            z = (resid - np.nanmedian(resid)) / mad
            sev = np.abs(z)
            mask = (z * direction) > 3.5
            rows += _events_from_mask(g.ts_hour, mask, sev, direction, "site", site, kpi, "stl_mad")
    return pd.DataFrame(rows)


def multivariate_anomalies(feat: pd.DataFrame, scorecard: pd.DataFrame, max_sites: int = 400) -> pd.DataFrame:
    from sklearn.decomposition import PCA
    from sklearn.ensemble import IsolationForest

    cols = [c for c in MULTIVAR_FEATURES if c in feat.columns]
    sites = scorecard.sort_values("impact_score", ascending=False).head(max_sites).site_id.tolist()
    d = feat[feat.site_id.isin(sites)].copy()
    X = d[cols].fillna(0.0).clip(-25, 25).to_numpy()
    if len(X) < 200:
        return pd.DataFrame()
    iso = IsolationForest(n_estimators=200, contamination=0.03, random_state=0).fit(X)
    iso_score = -iso.score_samples(X)
    pca = PCA(n_components=min(6, len(cols))).fit(X)
    recon = pca.inverse_transform(pca.transform(X))
    rec_err = np.sqrt(((X - recon) ** 2).mean(axis=1))
    d["_mv"] = 0.5 * (iso_score / (np.nanpercentile(iso_score, 99) or 1)) + 0.5 * (
        rec_err / (np.nanpercentile(rec_err, 99) or 1)
    )
    rows = []
    for site, g in d.sort_values("ts_hour").groupby("site_id"):
        s = g["_mv"].to_numpy()
        thr = np.nanmedian(s) + 3 * (1.4826 * np.nanmedian(np.abs(s - np.nanmedian(s))) or np.nanstd(s) or 1)
        rows += _events_from_mask(g.ts_hour, s > max(thr, 1.0), s, 1, "site", site,
                                  "multivariate", "iforest_pca")
    return pd.DataFrame(rows)


def changepoints(feat: pd.DataFrame, scorecard: pd.DataFrame, kpi: str = "tcp_client_rtt_ms",
                 max_sites: int = 150) -> pd.DataFrame:
    import ruptures as rpt

    sites = scorecard.sort_values("impact_score", ascending=False).head(max_sites).site_id.tolist()
    rows = []
    for site in sites:
        g = feat[feat.site_id == site].sort_values("ts_hour")
        y = g[kpi].astype(float).interpolate(limit_direction="both").to_numpy()
        if len(y) < 48:
            continue
        try:
            algo = rpt.Pelt(model="rbf", min_size=6).fit((y - np.nanmean(y)) / (np.nanstd(y) or 1))
            bkps = algo.predict(pen=8)
        except Exception:
            continue
        for b in bkps[:-1]:
            rows.append({"site_id": site, "kpi": kpi, "ts": str(g.ts_hour.iloc[min(b, len(g) - 1)])})
    return pd.DataFrame(rows)


def cluster_incidents(anoms: pd.DataFrame, db_path=None, gap_hours: int = 3) -> pd.DataFrame:
    """Group site anomalies that overlap in time and share transport topology into
    candidate incidents; match each to ground truth by site-set IoU."""
    if anoms.empty:
        return pd.DataFrame()
    con = connect(db_path)
    try:
        preagg = pd.read_sql_query(
            "SELECT p.site_id, p.link_id FROM dim_path_link p JOIN dim_link l ON l.link_id=p.link_id "
            "WHERE l.kind='preagg_uplink'", con
        )
    finally:
        con.close()
    link_of = preagg.set_index("site_id")["link_id"].to_dict()

    a = anoms[anoms.entity_type == "site"].copy()
    a["start"] = pd.to_datetime(a.start_ts)
    a["end"] = pd.to_datetime(a.end_ts)
    a["link"] = a.entity_id.map(link_of).fillna("NA")
    a = a.sort_values("start")

    clusters: list[dict] = []
    for link, g in a.groupby("link"):
        active: dict = None
        for _, r in g.iterrows():
            if active and r.start <= active["end"] + pd.Timedelta(hours=gap_hours):
                active["end"] = max(active["end"], r.end)
                active["sites"].add(r.entity_id)
                active["severity"] = max(active["severity"], r.severity)
            else:
                if active:
                    clusters.append(active)
                active = {"link": link, "start": r.start, "end": r.end,
                          "sites": {r.entity_id}, "severity": r.severity}
        if active:
            clusters.append(active)

    inc = load_incidents(db_path)
    rows = []
    for c in clusters:
        sites = c["sites"]
        # keep only material clusters: multi-site, or a strong single-site event
        if len(sites) < 2 and c["severity"] < 5.0:
            continue
        best_iou, best_id = 0.0, None
        for _, gi in inc.iterrows():
            gs = set(gi["sites"])
            if not gs:
                continue
            overlap_time = (min(c["end"], gi.end_ts) - max(c["start"], gi.start_ts)).total_seconds() > 0
            if not overlap_time:
                continue
            iou = len(sites & gs) / len(sites | gs)
            if iou > best_iou:
                best_iou, best_id = iou, gi.incident_id
        n_sites = len(sites)
        rows.append({
            "start_ts": str(c["start"]), "end_ts": str(c["end"]),
            "n_sites": n_sites, "n_links": 0 if c["link"] == "NA" else 1,
            "site_ids": json.dumps(sorted(sites)),
            "link_ids": json.dumps([] if c["link"] == "NA" else [c["link"]]),
            "severity": round(float(c["severity"]), 3),
            "predicted_class": "transport" if (c["link"] != "NA" and n_sites >= 3) else "ran",
            "confidence": round(float(np.clip(0.4 + 0.1 * n_sites, 0.4, 0.9)), 3),
            "matched_incident_id": best_id, "match_iou": round(best_iou, 3),
        })
    return pd.DataFrame(rows)
