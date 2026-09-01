"""Impact scoring & ranking -> site_scorecard.

Per-KPI degradation severity (robust exceedance vs the site's own + peer baseline),
weighted by sessions/users impacted, blended into a composite impact score, ranked. The
top slice is flagged as the Phase-2 audit priority list.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from networkanalysis.pipeline.features import HEADLINE_KPIS

SEVERITY_Z = 2.5  # robust-z beyond which a KPI-hour counts as degraded
DEFAULT_WEIGHTS = {
    "tcp_client_rtt_ms": 0.22,
    "tcp_fail_pct": 0.22,
    "dl_throughput_mbps": 0.20,
    "vonr_mos": 0.18,
    "youtube_qoe_mos": 0.18,
}


def _kpi_severity(feat: pd.DataFrame, kpi: str, direction: int) -> pd.DataFrame:
    """Severity per site: mean 'bad-direction' exceedance of the robust-z, session-weighted,
    plus the count of degraded hours."""
    z = feat[f"{kpi}__z"] * direction
    peer_z = feat[f"{kpi}__peer_z"] * direction
    combined = np.maximum(z.fillna(0), 0.5 * peer_z.fillna(0))
    exceed = np.clip(combined - SEVERITY_Z, 0, None)
    w = feat["sessions"].clip(lower=0) + 1.0
    tmp = pd.DataFrame({
        "site_id": feat.site_id, "ts_hour": feat.ts_hour,
        "exceed": exceed, "w": w, "degraded": (combined > SEVERITY_Z).astype(int),
    })
    agg = tmp.groupby("site_id").apply(
        lambda g: pd.Series({
            f"severity_{kpi}": float(np.average(g.exceed, weights=g.w)) if g.w.sum() else 0.0,
            f"degraded_hours_{kpi}": int(g.degraded.sum()),
        })
    )
    return agg


def _worst_window(feat: pd.DataFrame) -> pd.DataFrame:
    """Rolling 6h window with the largest summed headline exceedance, per site."""
    parts = []
    for kpi, d in HEADLINE_KPIS.items():
        z = np.clip(feat[f"{kpi}__z"] * d, 0, None).fillna(0)
        parts.append(z)
    feat = feat.assign(_badness=np.sum(parts, axis=0))
    rows = []
    for site, g in feat.sort_values("ts_hour").groupby("site_id"):
        r = g.set_index("ts_hour")["_badness"].rolling(6, min_periods=1).sum()
        if r.empty:
            continue
        end = r.idxmax()
        start = end - pd.Timedelta(hours=5)
        rows.append({"site_id": site, "worst_window_start": start, "worst_window_end": end,
                     "worst_badness": float(r.max())})
    return pd.DataFrame(rows)


def compute_scorecard(feat: pd.DataFrame, weights: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = weights or DEFAULT_WEIGHTS
    sev = pd.concat([_kpi_severity(feat, k, d) for k, d in HEADLINE_KPIS.items()], axis=1).fillna(0.0)

    # normalise each severity column to 0..1 by its 98th percentile, then weighted blend
    norm = sev.copy()
    for k in HEADLINE_KPIS:
        col = f"severity_{k}"
        p98 = np.nanpercentile(sev[col], 98) or 1.0
        norm[col] = np.clip(sev[col] / p98, 0, 1.5)
    composite = sum(norm[f"severity_{k}"] * w for k, w in weights.items())

    # impact weighting by sessions / users during degraded hours
    deg_mask_cols = [f"degraded_hours_{k}" for k in HEADLINE_KPIS]
    any_deg = sev[deg_mask_cols].sum(axis=1)
    site_load = feat.groupby("site_id").agg(sessions=("sessions", "sum"), users=("users", "mean"))
    frac_deg = (any_deg / max(feat.ts_hour.nunique(), 1)).clip(0, 1)
    sessions_impacted = site_load["sessions"] * frac_deg
    users_impacted = site_load["users"] * np.clip(frac_deg * 2.5, 0, 1)

    impact = composite * np.log1p(sessions_impacted.reindex(composite.index).fillna(0)) * (
        0.4 + 0.6 * np.clip(users_impacted.reindex(composite.index).fillna(0) / (users_impacted.median() or 1), 0, 3)
    )

    ww = _worst_window(feat).set_index("site_id")
    dim = feat.groupby("site_id")[["region", "morphology"]].first()

    sc = pd.DataFrame(index=composite.index)
    sc["region"] = dim["region"]
    sc["morphology"] = dim["morphology"]
    sc["impact_score"] = impact.round(4)
    for k in HEADLINE_KPIS:
        short = {"tcp_client_rtt_ms": "tcp_rtt", "tcp_fail_pct": "tcp_fail",
                 "dl_throughput_mbps": "throughput", "vonr_mos": "vonr",
                 "youtube_qoe_mos": "youtube"}[k]
        sc[f"severity_{short}"] = norm[f"severity_{k}"].round(4)
    sc["sessions_impacted"] = sessions_impacted.reindex(sc.index).fillna(0).round(1)
    sc["users_impacted"] = users_impacted.reindex(sc.index).fillna(0).round(1)
    sc = sc.join(ww[["worst_window_start", "worst_window_end"]])
    sc["worst_window_start"] = sc["worst_window_start"].astype(str)
    sc["worst_window_end"] = sc["worst_window_end"].astype(str)

    sc = sc.sort_values("impact_score", ascending=False)
    sc["rank"] = np.arange(1, len(sc) + 1)
    # target the ~75-120 band, but never more than ~60% of the market (small demo markets)
    n_priority = int(min(np.clip(round(0.09 * len(sc)), 75, 120), round(0.6 * len(sc))))
    sc["is_priority"] = (sc["rank"] <= n_priority).astype(int)
    sc = sc.reset_index().rename(columns={"index": "site_id"})

    worst = sc[["site_id", "worst_window_start", "worst_window_end"]].copy()
    return sc, worst
