"""Serving-cell resolution for raw crowdsourced tests.

The generator tags every Ookla test with its true site, but a realistic pipeline must
*resolve* the serving cell from the reported cell id (often missing/miscoded) plus geo and
signal. This re-derives it for a configurable fraction of tests and reports match
confidence - exercised in notebook 01 and surfaced as a data-quality metric.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from networkanalysis.db.database import connect


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def resolve_serving_cells(db_path=None, drop_fraction: float = 0.25, seed: int = 7) -> pd.DataFrame:
    con = connect(db_path)
    try:
        tests = pd.read_sql_query(
            "SELECT test_id, ts, site_id AS true_site_id, cell_id AS reported_cell_id, "
            "lat, lon, rsrp_dbm FROM fact_ookla_test", con
        )
        sites = pd.read_sql_query("SELECT site_id, lat, lon FROM dim_site", con)
    finally:
        con.close()
    if tests.empty:
        return tests

    rng = np.random.default_rng(seed)
    tests["reported_cell_id"] = tests["reported_cell_id"].where(
        rng.random(len(tests)) > drop_fraction, other=None
    )

    site_arr = sites[["lat", "lon"]].to_numpy()
    site_ids = sites["site_id"].to_numpy()
    resolved, dist, conf = [], [], []
    tll = tests[["lat", "lon"]].to_numpy()
    for i in range(len(tests)):
        rc = tests.reported_cell_id.iloc[i]
        if isinstance(rc, str) and rc:
            resolved.append(rc.split("-")[0])
            dist.append(0.0)
            conf.append(1.0)
            continue
        d = _haversine_km(tll[i, 0], tll[i, 1], site_arr[:, 0], site_arr[:, 1])
        order = np.argsort(d)[:3]
        # signal-weighted: closer + (rsrp proximity not available per candidate) -> distance only
        best = order[0]
        margin = d[order[1]] - d[order[0]]
        resolved.append(site_ids[best])
        dist.append(float(d[best]))
        conf.append(float(np.clip(margin / (d[order[0]] + 0.2), 0.2, 0.98)))

    tests["resolved_site_id"] = resolved
    tests["resolve_distance_km"] = np.round(dist, 3)
    tests["match_confidence"] = np.round(conf, 3)
    tests["correct"] = (tests.resolved_site_id == tests.true_site_id).astype(int)
    return tests
