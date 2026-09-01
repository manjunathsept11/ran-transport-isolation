"""Raw session-level records (Ookla SpeedTest tests, YouTube/Audio QoE sessions).

Sampled from the per-bin site state produced by :mod:`model`: a Poisson number of
sessions per site-bin (scaled by the diurnal load and feed config), each with per-session
noise around the bin KPI. These carry the true "sessions / users impacted" counts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from networkanalysis.config.models import GenConfig
from networkanalysis.topology.generate import Topology

DEVICE_CLASSES = np.array(["flagship", "midrange", "entry", "iot"])
DEVICE_P = np.array([0.34, 0.42, 0.19, 0.05])


def _primary_cell(topo: Topology) -> pd.Series:
    """Pick each site's mid-band cell in sector 1 as the 'reported' serving cell."""
    c = topo.cells.sort_values(["site_id", "sector", "carrier_ghz"])
    first = c.groupby("site_id").nth(len(c.band.unique()) // 2 if False else 0)
    return first.set_index("site_id")["cell_id"]


def generate_sessions(cfg: GenConfig, topo: Topology, site_bin_files: list[str], raw_dir,
                      progress=None) -> dict[str, list[str]]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    rng = np.random.default_rng(cfg.seed + 4242)
    cell_of = _primary_cell(topo)
    site_ll = topo.sites.set_index("site_id")[["lat", "lon"]]
    bin_hours = cfg.bin_seconds / 3600.0
    ookla_rate = cfg.feeds.ookla.tests_per_site_busy_hour.central * bin_hours
    qoe_rate = cfg.feeds.qoe.sessions_per_site_busy_hour.central * bin_hours
    yt_frac = cfg.feeds.qoe.youtube_fraction

    files = {"ookla_test": [], "qoe_session": []}

    for fi, f in enumerate(site_bin_files):
        sb = pq.read_table(f).to_pandas()
        day = f.split("dt=")[-1].replace(".parquet", "")
        # diurnal scaling proxy: sessions track offered load relative to its site mean
        site_mean = sb.groupby("site_id")["offered_mbps"].transform("mean").to_numpy()
        load_ratio = np.clip(sb.offered_mbps.to_numpy() / np.maximum(site_mean, 1e-6), 0.05, 3.0)
        avail = sb.availability.to_numpy()

        # ---- Ookla ----
        lam = ookla_rate * load_ratio * avail
        k = rng.poisson(np.clip(lam, 0, None))
        if k.sum() > 0:
            ridx = np.repeat(np.arange(len(sb)), k)
            r = sb.iloc[ridx].reset_index(drop=True)
            m = len(r)
            jitter_t = rng.uniform(0, cfg.bin_seconds, m).astype("timedelta64[s]")
            dl = np.clip(r.dl_throughput_mbps.to_numpy() * rng.lognormal(0, 0.22, m), 0.05, None)
            ul = np.clip(r.ul_throughput_mbps.to_numpy() * rng.lognormal(0, 0.25, m), 0.02, None)
            lat = np.clip(r.loaded_latency_ms.to_numpy() * rng.lognormal(0, 0.18, m), 3, None)
            rsrp = r.rsrp_dbm.to_numpy() + rng.normal(0, 2.5, m)
            rsrq = r.rsrq_db.to_numpy() + rng.normal(0, 1.2, m)
            sll = site_ll.reindex(r.site_id).to_numpy()
            ookla = pd.DataFrame({
                "test_id": [f"OK{day}{fi}{i:06d}" for i in range(m)],
                "ts": r.ts.to_numpy() + jitter_t,
                "site_id": r.site_id.to_numpy(),
                "cell_id": cell_of.reindex(r.site_id).to_numpy(),
                "lat": np.round(sll[:, 0] + rng.normal(0, 0.004, m), 6),
                "lon": np.round(sll[:, 1] + rng.normal(0, 0.004, m), 6),
                "device_class": rng.choice(DEVICE_CLASSES, m, p=DEVICE_P),
                "dl_mbps": np.round(dl, 3), "ul_mbps": np.round(ul, 3),
                "loaded_latency_ms": np.round(lat, 2),
                "rsrp_dbm": np.round(rsrp, 2), "rsrq_db": np.round(rsrq, 2),
            })
            d = raw_dir / "ookla_test"
            d.mkdir(parents=True, exist_ok=True)
            fp = str(d / f"dt={day}.parquet")
            pq.write_table(pa.Table.from_pandas(ookla, preserve_index=False), fp)
            files["ookla_test"].append(fp)

        # ---- QoE ----
        lam = qoe_rate * load_ratio * avail
        k = rng.poisson(np.clip(lam, 0, None))
        if k.sum() > 0:
            ridx = np.repeat(np.arange(len(sb)), k)
            r = sb.iloc[ridx].reset_index(drop=True)
            m = len(r)
            jitter_t = rng.uniform(0, cfg.bin_seconds, m).astype("timedelta64[s]")
            is_yt = rng.random(m) < yt_frac
            mos = np.where(
                is_yt,
                np.clip(r.youtube_qoe_mos.to_numpy() + rng.normal(0, 0.25, m), 1, 5),
                np.clip(r.vonr_mos.to_numpy() + rng.normal(0, 0.2, m), 1, 4.5),
            )
            reb = np.clip(r.rebuffer_ratio.to_numpy() * rng.lognormal(0, 0.4, m), 0, 1)
            startup = np.clip(700 + 90 * r.tcp_client_rtt_ms.to_numpy() / 20 + rng.normal(0, 250, m), 120, None)
            bitrate = np.clip(r.dl_throughput_mbps.to_numpy() * 900 * rng.uniform(0.5, 0.9, m), 120, 12000)
            qoe = pd.DataFrame({
                "session_id": [f"QS{day}{fi}{i:06d}" for i in range(m)],
                "ts": r.ts.to_numpy() + jitter_t,
                "site_id": r.site_id.to_numpy(),
                "cell_id": cell_of.reindex(r.site_id).to_numpy(),
                "service": np.where(is_yt, "youtube", "audio"),
                "mos": np.round(mos, 3),
                "rebuffer_ratio": np.round(reb, 4),
                "startup_ms": np.round(startup, 0),
                "bitrate_kbps": np.round(bitrate, 0),
            })
            d = raw_dir / "qoe_session"
            d.mkdir(parents=True, exist_ok=True)
            fp = str(d / f"dt={day}.parquet")
            pq.write_table(pa.Table.from_pandas(qoe, preserve_index=False), fp)
            files["qoe_session"].append(fp)

        if progress:
            progress(day, fi + 1)
    return files
