"""The structural causal metric model.

Layered generation: demand -> radio -> transport (queueing) -> session/app KPIs. Metrics
are derived from shared latent state (load, path delay, radio quality) so their
correlations are physical, not bolted-on noise. Incident effects are injected at the state
level before KPIs are derived.

Produces per-bin fact tables written as day-partitioned parquet:
  site_bin, link_bin, twamp_5min, sevone_5min, n3_5min
Raw session records (Ookla, QoE) are produced separately in :mod:`sessions`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse

from networkanalysis.config.models import GenConfig
from networkanalysis.generate.incidents import effect_for
from networkanalysis.generate.timeprofile import load_shape
from networkanalysis.topology.generate import Topology

RNG_SALT = 0x5EED
MORPH_RSRP = {"dense_urban": -88.0, "urban": -94.0, "suburban": -98.0, "rural": -104.0}
ERLANG_MBPS = 2.3
INTERNET_RTT_FLOOR = 6.0


def _emodel_mos(one_way_delay_ms: np.ndarray, loss_pct: np.ndarray, jitter_ms: np.ndarray) -> np.ndarray:
    """ITU-T G.107 E-model -> MOS (1..4.5), simplified for packet voice / VoNR."""
    d = one_way_delay_ms + 2.0 * jitter_ms
    id_ = np.where(d < 177.3, 0.024 * d, 0.024 * d + 0.11 * (d - 177.3))
    ppl = np.clip(loss_pct, 0, 100)
    ie = 5 + 90 * ppl / (ppl + 6.5)
    r = np.clip(93.2 - id_ - ie, 0, 100)
    mos = 1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r)
    return np.clip(mos, 1.0, 4.5)


@dataclass
class ModelOutputs:
    files: dict[str, list[str]] = field(default_factory=dict)
    site_static: pd.DataFrame = field(default_factory=pd.DataFrame)


def _static_site_state(cfg: GenConfig, topo: Topology) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed ^ RNG_SALT)
    s = topo.sites.copy().reset_index(drop=True)
    n = len(s)
    bh = cfg.baseline("site_busy_hour_erlangs").sample(rng, n)
    scale = s.morphology.map(
        {"dense_urban": 1.8, "urban": 1.25, "suburban": 0.8, "rural": 0.45}
    ).to_numpy()
    s["busy_hour_erlangs"] = np.clip(bh * scale, 2, None)
    s["rsrp_base_dbm"] = s.morphology.map(MORPH_RSRP).to_numpy() + rng.normal(0, 3.0, n)
    s["rsrq_base_db"] = cfg.baseline("rsrq_db").sample(rng, n)
    s["radio_capacity_mbps"] = s.design_capacity_mbps.to_numpy() * rng.uniform(0.75, 1.0, n)
    s["server_rtt_ms"] = np.clip(cfg.baseline("tcp_server_rtt_ms").sample(rng, n), INTERNET_RTT_FLOOR, None)
    return s


def _static_link_state(cfg: GenConfig, topo: Topology) -> pd.DataFrame:
    rng = np.random.default_rng((cfg.seed ^ RNG_SALT) + 1)
    lk = topo.links.copy().reset_index(drop=True)
    n = len(lk)
    lk["base_delay_ms"] = cfg.baseline("link_base_delay_ms").sample(rng, n)
    lk["base_jitter_ms"] = cfg.baseline("link_base_jitter_ms").sample(rng, n)
    lk["base_loss_pct"] = cfg.baseline("link_base_loss_pct").sample(rng, n)
    mw = (lk.media == "microwave").to_numpy()
    lk.loc[mw, "base_jitter_ms"] *= 1.7
    lk.loc[mw, "base_loss_pct"] += 0.04
    lk["service_ms"] = 8000.0 / np.maximum(lk.capacity_mbps.to_numpy(), 1.0)
    return lk


def _incidence(topo: Topology, links: pd.DataFrame, sites: pd.DataFrame) -> sparse.csr_matrix:
    lidx = {l: i for i, l in enumerate(links.link_id)}
    sidx = {s: i for i, s in enumerate(sites.site_id)}
    rows, cols = [], []
    for sid, grp in topo.path_links.groupby("site_id"):
        if sid not in sidx:
            continue
        j = sidx[sid]
        for lid in grp.link_id:
            if lid in lidx:
                rows.append(lidx[lid])
                cols.append(j)
    return sparse.csr_matrix(
        (np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(len(links), len(sites))
    )


def _parse_incidents(inc_df: pd.DataFrame) -> list[dict]:
    events = []
    for _, r in inc_df.iterrows():
        events.append(
            {
                "kind": r.kind,
                "start": pd.Timestamp(r.start_ts),
                "end": pd.Timestamp(r.end_ts),
                "sites": set(json.loads(r.affected_site_ids or "[]")),
                "links": set(json.loads(r.affected_link_ids or "[]")),
                "eff": effect_for(r.kind, float(r.magnitude)),
            }
        )
    return events


def _round32(a: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(a).reshape(-1).astype(np.float32), 4)


def run_model(cfg, topo, inc_df, ts_index, raw_dir, progress=None) -> ModelOutputs:
    import pyarrow as pa
    import pyarrow.parquet as pq

    sites = _static_site_state(cfg, topo)
    links = _static_link_state(cfg, topo)
    n_sites, n_links = len(sites), len(links)
    site_ids = sites.site_id.to_numpy()
    link_ids = links.link_id.to_numpy()
    link_pos = {l: i for i, l in enumerate(link_ids)}
    site_pos = {s: i for i, s in enumerate(site_ids)}

    incidence_T = _incidence(topo, links, sites).T.toarray()          # (n_sites, n_links)
    incidence = incidence_T.T                                         # (n_links, n_sites)

    path_mat = np.full((n_sites, 3), -1, dtype=int)
    for sid, grp in topo.path_links.sort_values("hop_index").groupby("site_id"):
        if sid not in site_pos:
            continue
        for h, lid in enumerate(grp.link_id.tolist()[:3]):
            if lid in link_pos:
                path_mat[site_pos[sid], h] = link_pos[lid]

    events = _parse_incidents(inc_df)
    shape_all = load_shape(ts_index)
    shape_min, shape_ptp = float(np.min(shape_all)), float(np.ptp(shape_all)) + 1e-9
    rng = np.random.default_rng(cfg.seed + 7)

    days = pd.Series(pd.DatetimeIndex(ts_index).date).astype(str)
    out = ModelOutputs(files={k: [] for k in ("site_bin", "link_bin", "twamp_5min", "sevone_5min", "n3_5min")})

    for day, idx_ser in pd.Series(np.arange(len(ts_index))).groupby(days):
        pos = idx_ser.to_numpy()
        tb = pd.DatetimeIndex(ts_index[pos])
        B = len(pos)
        shape = shape_all[pos][:, None]
        bh_env = (0.35 + 0.9 * (shape_all[pos] - shape_min) / shape_ptp)[:, None]
        minute_of = (tb.astype("int64").to_numpy() // 60_000_000_000)

        # ---- incident state deltas for this day ----------------------
        d_rsrp = np.zeros((B, n_sites)); d_rsrq = np.zeros((B, n_sites)); d_prb = np.zeros((B, n_sites))
        radio_cap_mult = np.ones((B, n_sites)); site_avail = np.ones((B, n_sites))
        d_tcp_fail = np.zeros((B, n_sites)); d_retrans = np.zeros((B, n_sites))
        d_l_loss = np.zeros((B, n_links)); d_l_jit = np.zeros((B, n_links)); d_l_delay = np.zeros((B, n_links))
        l_cap_mult = np.ones((B, n_links)); d_queue = np.zeros((B, n_links))
        d_crc = np.zeros((B, n_links)); d_discard = np.zeros((B, n_links)); l_avail = np.ones((B, n_links))

        for ev in events:
            act = (tb >= ev["start"]) & (tb < ev["end"])
            if not act.any():
                continue
            eff = ev["eff"]
            total = max((ev["end"] - ev["start"]).total_seconds(), 60.0)
            span = np.clip((tb - ev["start"]).total_seconds().to_numpy() / total, 0, 1)
            ramp = np.clip(np.minimum(span / 0.12, (1 - span) / 0.12), 0, 1)
            env = act.astype(float) * (0.25 + 0.75 * ramp)
            if eff.weather_like:
                env = env * (0.55 + 0.45 * np.sqrt(np.sin(np.pi * span)))
            if eff.flapping:
                env = env * (((np.floor(minute_of / 8) % 2) == 0) * 0.7 + 0.3)
            if eff.busy_hour_weighted:
                env = env * bh_env[:, 0]
            env = env[:, None]

            s_idx = np.array([site_pos[s] for s in ev["sites"] if s in site_pos], dtype=int)
            l_idx = np.array([link_pos[l] for l in ev["links"] if l in link_pos], dtype=int)
            if s_idx.size:
                d_rsrp[:, s_idx] += eff.rsrp_offset_db * env
                d_rsrq[:, s_idx] += eff.rsrq_offset_db * env
                d_prb[:, s_idx] += eff.prb_extra * env
                radio_cap_mult[:, s_idx] *= 1 - (1 - eff.radio_cap_mult) * env
                d_tcp_fail[:, s_idx] += eff.tcp_fail_add_pct * env
                d_retrans[:, s_idx] += eff.retrans_add_pct * env
                if eff.avail_mult == 0.0:
                    site_avail[:, s_idx] *= 1 - env * 0.98
            if l_idx.size:
                d_l_loss[:, l_idx] += eff.loss_add_pct * env
                d_l_jit[:, l_idx] += eff.jitter_add_ms * env
                d_l_delay[:, l_idx] += eff.delay_add_ms * env
                l_cap_mult[:, l_idx] *= 1 - (1 - eff.link_cap_mult) * env
                d_queue[:, l_idx] += eff.queue_add * env
                d_crc[:, l_idx] += eff.crc_rate_add * env
                d_discard[:, l_idx] += eff.discard_add * env
                if eff.avail_mult == 0.0:
                    l_avail[:, l_idx] *= 1 - env * 0.98

        # ---- demand -------------------------------------------------
        base_erl = sites.busy_hour_erlangs.to_numpy()[None, :]
        site_offered = base_erl * shape * rng.lognormal(0, 0.10, (B, n_sites)) * ERLANG_MBPS * site_avail

        # ---- link queueing ----------------------------------------
        link_offered = site_offered @ incidence.T
        cap_eff = links.capacity_mbps.to_numpy()[None, :] * l_cap_mult
        rho = np.clip(link_offered / np.maximum(cap_eff, 1.0), 0, 0.999)
        queue_occ = np.clip(rho / (1 - rho) / 25.0 + d_queue, 0, 4.0)
        svc = links.service_ms.to_numpy()[None, :]
        link_delay = links.base_delay_ms.to_numpy()[None, :] + queue_occ * svc * 6.0 + d_l_delay
        link_jitter = np.clip(
            links.base_jitter_ms.to_numpy()[None, :] * (1 + 1.5 * rho) + d_l_jit
            + np.abs(rng.normal(0, 0.15, (B, n_links))),
            0.01, None,
        )
        link_loss = np.clip(
            links.base_loss_pct.to_numpy()[None, :] + np.clip((rho - 0.9) * 12.0, 0, None) ** 1.5 + d_l_loss,
            0, 100,
        )
        link_util = np.clip(rho * 100 + rng.normal(0, 1.5, (B, n_links)), 0, 100)
        link_discards = (d_discard + np.clip(rho - 0.92, 0, None) * 0.02) * np.maximum(link_offered, 0)
        is_mw = (links.media.to_numpy() == "microwave")[None, :]
        link_crc = (d_crc + np.where(is_mw, 0.02, 0.005)) * (1 + rng.random((B, n_links)) * 0.3)

        # ---- per-site path rollup --------------------------------
        pth_delay = np.zeros((B, n_sites)); pth_jsq = np.zeros((B, n_sites))
        keep = np.ones((B, n_sites)); pth_cap = np.full((B, n_sites), 1e9); pth_avail = np.ones((B, n_sites))
        for hop in range(3):
            idx = path_mat[:, hop]
            v = idx >= 0
            gd = np.zeros((B, n_sites)); gj = np.zeros((B, n_sites)); gl = np.zeros((B, n_sites))
            gc = np.full((B, n_sites), 1e9); ga = np.ones((B, n_sites))
            gd[:, v] = link_delay[:, idx[v]]
            gj[:, v] = link_jitter[:, idx[v]]
            gl[:, v] = link_loss[:, idx[v]]
            gc[:, v] = cap_eff[:, idx[v]]
            ga[:, v] = l_avail[:, idx[v]]
            pth_delay += gd
            pth_jsq += gj ** 2
            keep *= 1 - np.clip(gl, 0, 100) / 100.0
            pth_cap = np.minimum(pth_cap, np.where(gc <= 0, 1e9, gc))
            pth_avail = np.minimum(pth_avail, ga)
        pth_jitter = np.sqrt(pth_jsq)
        pth_loss = (1 - keep) * 100.0
        avail = np.minimum(site_avail, pth_avail)

        # ---- radio ----------------------------------------------
        rsrp = sites.rsrp_base_dbm.to_numpy()[None, :] + d_rsrp + rng.normal(0, 1.0, (B, n_sites))
        rho_site = np.clip(site_offered / (sites.radio_capacity_mbps.to_numpy()[None, :] + 1e-6), 0, 1.3)
        prb_util = np.clip(rho_site * 78 + d_prb + rng.normal(0, 2.5, (B, n_sites)), 0, 100)
        rsrq = (
            sites.rsrq_base_db.to_numpy()[None, :] + d_rsrq
            - np.clip(prb_util - 60, 0, None) * 0.05 + rng.normal(0, 0.6, (B, n_sites))
        )
        sched_delay = 2.0 + 30.0 * np.clip(prb_util / 100, 0, 1) ** 3 + np.clip(-(rsrp + 110) / 8, 0, None)
        radio_cap = (
            sites.radio_capacity_mbps.to_numpy()[None, :] * radio_cap_mult
            * np.clip(1 - (prb_util - 55) / 90, 0.08, 1.0)
            * np.clip(1 + (rsrq + 12) / 20, 0.25, 1.15)
        )

        # ---- session / app -------------------------------------
        server_rtt = sites.server_rtt_ms.to_numpy()[None, :] + rng.normal(0, 1.2, (B, n_sites))
        client_rtt = np.clip(sched_delay + 2.0 * pth_delay + rng.normal(0, 2.0, (B, n_sites)), 3, None)
        radio_bler = np.clip((-rsrq - 8) * 0.4, 0, None) + np.clip(prb_util - 92, 0, None) * 0.05
        eff_loss = np.clip(pth_loss + radio_bler * 0.3, 0, 100)
        retrans = np.clip(0.4 + 0.9 * eff_loss + d_retrans + np.abs(rng.normal(0, 0.15, (B, n_sites))), 0, 100)
        tcp_fail = np.clip(
            0.3 + 0.25 * eff_loss + np.clip(client_rtt - 120, 0, None) * 0.01
            + d_tcp_fail + np.clip(prb_util - 96, 0, None) * 0.2,
            0, 100,
        )
        bdp = 210.0 * (35.0 / np.clip(client_rtt + server_rtt, 8, None)) * np.clip(1 - retrans / 130, 0.1, 1)
        dl = np.clip(np.minimum(np.minimum(radio_cap, pth_cap), bdp) * avail, 0.02, None)
        dl = dl * (0.6 + 0.4 / np.clip(1 + np.exp((prb_util - 95) / 3), 1, None))
        ul = dl * 0.13 * np.clip(1 - radio_bler / 30, 0.3, 1)
        loaded_latency = client_rtt + server_rtt + np.clip(rho_site * 40, 0, 300)
        vonr = np.where(avail > 0.5, _emodel_mos(pth_delay + sched_delay / 2, eff_loss, pth_jitter), 1.0)

        need = 3.2
        deficit = np.clip(need - dl, 0, None) / need
        rebuffer = np.clip(1 / (1 + np.exp(-(deficit * 6 + eff_loss * 0.2 - 2.0))), 0, 1) * (deficit > 0)
        yt = np.where(avail > 0.5, np.clip(4.6 - 3.2 * rebuffer - 0.02 * np.clip(loaded_latency - 60, 0, None) / 10, 1, 5), 1.0)

        users = np.clip(base_erl * shape * 3.0 * rng.lognormal(0, 0.10, (B, n_sites)), 0, None) * avail
        flows = users * rng.uniform(2.5, 4.0, (B, n_sites))

        # ---- write chunk --------------------------------------
        tt = np.repeat(tb.values, n_sites)
        ss = np.tile(site_ids, B)
        site_bin = pd.DataFrame({
            "ts": tt, "site_id": ss,
            "offered_mbps": _round32(site_offered), "prb_util_pct": _round32(prb_util),
            "rsrp_dbm": _round32(rsrp), "rsrq_db": _round32(rsrq),
            "sched_delay_ms": _round32(sched_delay), "path_delay_ms": _round32(pth_delay),
            "path_jitter_ms": _round32(pth_jitter), "path_loss_pct": _round32(pth_loss),
            "path_capacity_mbps": _round32(np.minimum(pth_cap, 5e4)), "radio_capacity_mbps": _round32(radio_cap),
            "tcp_client_rtt_ms": _round32(client_rtt), "tcp_server_rtt_ms": _round32(server_rtt),
            "tcp_fail_pct": _round32(tcp_fail), "retrans_pct": _round32(retrans), "vonr_mos": _round32(vonr),
            "dl_throughput_mbps": _round32(dl), "ul_throughput_mbps": _round32(ul),
            "loaded_latency_ms": _round32(loaded_latency), "youtube_qoe_mos": _round32(yt),
            "rebuffer_ratio": _round32(rebuffer), "sessions": _round32(flows), "users": _round32(users),
            "availability": _round32(avail),
        })
        lt = np.repeat(tb.values, n_links)
        ll = np.tile(link_ids, B)
        link_bin = pd.DataFrame({
            "ts": lt, "link_id": ll, "offered_mbps": _round32(link_offered), "util_pct": _round32(link_util),
            "queue_occ": _round32(queue_occ), "delay_ms": _round32(link_delay), "jitter_ms": _round32(link_jitter),
            "loss_pct": _round32(link_loss), "discards_pps": _round32(link_discards),
            "crc_rate": _round32(link_crc), "availability": _round32(l_avail),
        })
        twamp = pd.DataFrame({
            "ts": lt, "link_id": ll, "rtt_ms": _round32(2 * link_delay), "owd_ms": _round32(link_delay),
            "jitter_ms": _round32(link_jitter), "frame_loss_pct": _round32(link_loss),
        })
        sevone = pd.DataFrame({
            "ts": lt, "link_id": ll, "in_util_pct": _round32(link_util),
            "out_util_pct": _round32(np.clip(link_util * 0.85, 0, 100)), "queue_depth": _round32(queue_occ * 100),
            "discards": _round32(link_discards * 300), "crc_errors": _round32(link_crc * 1000),
            "if_errors": _round32(link_crc * 400),
        })
        n3 = pd.DataFrame({
            "ts": tt, "site_id": ss, "tcp_client_rtt_ms": _round32(client_rtt),
            "tcp_server_rtt_ms": _round32(server_rtt), "tcp_fail_pct": _round32(tcp_fail),
            "retrans_pct": _round32(retrans), "vonr_mos": _round32(vonr),
            "flow_count": _round32(flows), "user_count": _round32(users),
        })

        for name, df_ in (("site_bin", site_bin), ("link_bin", link_bin), ("twamp_5min", twamp),
                          ("sevone_5min", sevone), ("n3_5min", n3)):
            d = raw_dir / name
            d.mkdir(parents=True, exist_ok=True)
            fp = str(d / f"dt={day}.parquet")
            pq.write_table(pa.Table.from_pandas(df_, preserve_index=False), fp)
            out.files[name].append(fp)
        if progress:
            progress(day, len(out.files["site_bin"]))

    out.site_static = sites
    return out
