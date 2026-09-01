"""Fault injection - schedule labelled incidents and describe their multi-metric signature.

Every incident becomes a row in ``dim_incident`` (the ground truth for attribution and RCA
scoring). :func:`schedule_incidents` turns the config's explicit + auto incident specs into
concrete targets/timespans; :func:`effect_for` returns the per-bin state deltas the metric
model applies while an incident is active.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from networkanalysis.config.models import GenConfig, IncidentSpec
from networkanalysis.topology.generate import Topology

# transport kinds that fail a *shared* uplink (whole cluster) vs an individual access link
SHARED_LINK_KINDS = {"congested_backhaul", "fiber_degradation", "queue_drops", "routing_flap"}
ACCESS_LINK_KINDS = {"microwave_fade", "sfp_errors", "mtu_blackhole"}


@dataclass
class IncidentEffect:
    """Per-bin state deltas applied while an incident is active (already scaled by magnitude)."""

    # radio (site / sector)
    rsrp_offset_db: float = 0.0
    rsrq_offset_db: float = 0.0
    prb_extra: float = 0.0            # additive PRB utilisation points
    radio_cap_mult: float = 1.0      # multiply radio capacity
    sector_out: int | None = None    # sector index taken out of service
    # transport (link)
    loss_add_pct: float = 0.0
    jitter_add_ms: float = 0.0
    delay_add_ms: float = 0.0
    link_cap_mult: float = 1.0
    queue_add: float = 0.0           # additive normalised queue occupancy
    crc_rate_add: float = 0.0        # additive CRC error rate (per Mpkt)
    discard_add: float = 0.0
    # session / app
    tcp_fail_add_pct: float = 0.0
    retrans_add_pct: float = 0.0
    # availability (0 => full outage of all feeds for the entity)
    avail_mult: float = 1.0
    # behavioural flags
    busy_hour_weighted: bool = False  # effect scales with the diurnal load shape
    flapping: bool = False            # effect pulses on/off within the window
    weather_like: bool = False        # slow envelope over the window


def _kind_effect(kind: str, mag: float) -> IncidentEffect:
    m = float(mag)
    if kind == "microwave_fade":
        return IncidentEffect(
            loss_add_pct=3.5 * m, jitter_add_ms=9.0 * m, delay_add_ms=4.0 * m,
            link_cap_mult=1 - 0.45 * m, crc_rate_add=1.5 * m, weather_like=True,
        )
    if kind == "congested_backhaul":
        return IncidentEffect(
            link_cap_mult=1 - 0.5 * m, queue_add=0.55 * m, loss_add_pct=1.2 * m,
            jitter_add_ms=6.0 * m, delay_add_ms=12.0 * m, discard_add=0.03 * m,
            busy_hour_weighted=True,
        )
    if kind == "fiber_degradation":
        return IncidentEffect(
            loss_add_pct=5.5 * m, delay_add_ms=6.0 * m, jitter_add_ms=4.0 * m,
            link_cap_mult=1 - 0.7 * m, crc_rate_add=4.0 * m, retrans_add_pct=6 * m,
        )
    if kind == "sfp_errors":
        return IncidentEffect(
            loss_add_pct=1.8 * m, crc_rate_add=6.0 * m, retrans_add_pct=5 * m,
            jitter_add_ms=2.5 * m, flapping=True,
        )
    if kind == "queue_drops":
        return IncidentEffect(
            queue_add=0.6 * m, discard_add=0.05 * m, loss_add_pct=2.0 * m,
            jitter_add_ms=5.0 * m, delay_add_ms=8.0 * m, busy_hour_weighted=True,
        )
    if kind == "routing_flap":
        return IncidentEffect(
            delay_add_ms=25 * m, loss_add_pct=4.0 * m, jitter_add_ms=14 * m,
            tcp_fail_add_pct=3 * m, flapping=True,
        )
    if kind == "mtu_blackhole":
        return IncidentEffect(
            tcp_fail_add_pct=9 * m, retrans_add_pct=8 * m, loss_add_pct=0.8 * m,
            link_cap_mult=1 - 0.35 * m,
        )
    # --- RAN ---
    if kind == "sleeping_sector":
        return IncidentEffect(radio_cap_mult=1 - 0.9 * m, rsrp_offset_db=-14 * m, sector_out=1)
    if kind == "external_interference":
        return IncidentEffect(
            rsrq_offset_db=-7.5 * m, radio_cap_mult=1 - 0.4 * m, retrans_add_pct=3 * m,
            busy_hour_weighted=True,
        )
    if kind == "coverage_hole":
        return IncidentEffect(rsrp_offset_db=-11 * m, radio_cap_mult=1 - 0.3 * m)
    if kind == "cell_overshoot":
        return IncidentEffect(rsrq_offset_db=-5 * m, radio_cap_mult=1 - 0.2 * m)
    if kind == "prb_exhaustion":
        return IncidentEffect(prb_extra=45 * m, radio_cap_mult=1 - 0.55 * m, busy_hour_weighted=True)
    if kind == "vswr":
        return IncidentEffect(radio_cap_mult=1 - 0.35 * m, rsrp_offset_db=-4 * m, retrans_add_pct=2 * m)
    # --- shared ---
    if kind == "site_power_outage":
        return IncidentEffect(avail_mult=0.0)
    if kind == "severe_weather":
        return IncidentEffect(
            loss_add_pct=2.5 * m, jitter_add_ms=6 * m, rsrp_offset_db=-3 * m,
            link_cap_mult=1 - 0.3 * m, weather_like=True,
        )
    if kind == "transport_node_reload":
        return IncidentEffect(avail_mult=0.0, loss_add_pct=8 * m, flapping=True)
    return IncidentEffect()


def effect_for(kind: str, magnitude: float) -> IncidentEffect:
    return _kind_effect(kind, magnitude)


@dataclass
class ScheduledIncident:
    incident_id: str
    incident_class: str
    kind: str
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    magnitude: float
    affected_site_ids: list[str] = field(default_factory=list)
    affected_link_ids: list[str] = field(default_factory=list)
    affected_sectors: list[str] = field(default_factory=list)  # "S00001-2"
    root_entity: str = ""
    root_entity_type: str = ""  # link | sector | site | router
    auto: bool = False

    def to_row(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "incident_class": self.incident_class,
            "kind": self.kind,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "magnitude": round(self.magnitude, 4),
            "root_entity": self.root_entity,
            "root_entity_type": self.root_entity_type,
            "n_affected_sites": len(self.affected_site_ids),
            "affected_site_ids": json.dumps(self.affected_site_ids),
            "affected_link_ids": json.dumps(self.affected_link_ids),
            "affected_sectors": json.dumps(self.affected_sectors),
            "auto_generated": int(self.auto),
        }


def _sites_on_link(topo: Topology, link_id: str) -> list[str]:
    return topo.path_links.loc[topo.path_links.link_id == link_id, "site_id"].unique().tolist()


def _pick_sites(topo: Topology, rng, spec_or_kwargs, n: int) -> list[str]:
    df = topo.sites
    region = getattr(spec_or_kwargs, "region", None)
    morph = getattr(spec_or_kwargs, "morphology", None)
    if region:
        df = df[df.region == region]
    if morph:
        df = df[df.morphology == morph]
    if df.empty:
        df = topo.sites
    n = min(n, len(df))
    return rng.choice(df.site_id.to_numpy(), size=n, replace=False).tolist()


def _materialise(
    topo: Topology, rng, iid: str, spec: IncidentSpec, start: pd.Timestamp, end: pd.Timestamp,
    auto: bool = False,
) -> ScheduledIncident:
    kind = spec.kind
    cls = spec.incident_class
    si = ScheduledIncident(iid, cls, kind, start, end, spec.magnitude, auto=auto)

    if cls == "transport" and kind in SHARED_LINK_KINDS:
        uplinks = topo.links[topo.links.kind == "preagg_uplink"]
        n_links = max(1, int(np.ceil(spec.n_targets / 12)))
        chosen = rng.choice(uplinks.link_id.to_numpy(), size=min(n_links, len(uplinks)), replace=False)
        si.affected_link_ids = list(chosen)
        sites: set[str] = set()
        for lid in chosen:
            sites.update(_sites_on_link(topo, lid))
        si.affected_site_ids = sorted(sites)
        si.root_entity = ";".join(sorted(chosen))
        si.root_entity_type = "link"

    elif cls == "transport" and kind in ACCESS_LINK_KINDS:
        pool = topo.sites
        if kind == "microwave_fade":
            pool = pool[pool.backhaul_type == "microwave"]
        if spec.region:
            pool = pool[pool.region == spec.region]
        if pool.empty:
            pool = topo.sites
        chosen = rng.choice(pool.site_id.to_numpy(), size=min(spec.n_targets, len(pool)), replace=False)
        si.affected_site_ids = sorted(chosen)
        acc = topo.links[(topo.links.kind == "access") & (topo.links.endpoint_a.isin(chosen))]
        si.affected_link_ids = acc.link_id.tolist()
        si.root_entity = ";".join(sorted(si.affected_link_ids))
        si.root_entity_type = "link"

    elif cls == "ran" and kind == "sleeping_sector":
        chosen = _pick_sites(topo, rng, spec, spec.n_targets)
        sector = int(rng.integers(1, 4))
        si.affected_site_ids = sorted(chosen)
        si.affected_sectors = [f"{s}-{sector}" for s in chosen]
        si.root_entity = ";".join(si.affected_sectors)
        si.root_entity_type = "sector"

    elif cls == "ran":
        chosen = _pick_sites(topo, rng, spec, spec.n_targets)
        si.affected_site_ids = sorted(chosen)
        si.root_entity = ";".join(sorted(chosen))
        si.root_entity_type = "site"

    else:  # shared
        if kind == "transport_node_reload":
            preaggs = topo.routers[topo.routers.role == "pre_aggregation"]
            rtr = rng.choice(preaggs.router_id.to_numpy())
            uplink = topo.links[
                (topo.links.kind == "preagg_uplink") & (topo.links.endpoint_a == rtr)
            ].link_id.tolist()
            si.affected_link_ids = uplink
            si.affected_site_ids = sorted(set().union(*[_sites_on_link(topo, l) for l in uplink])) if uplink else []
            si.root_entity = rtr
            si.root_entity_type = "router"
        else:
            chosen = _pick_sites(topo, rng, spec, spec.n_targets)
            si.affected_site_ids = sorted(chosen)
            if kind == "severe_weather":
                acc = topo.links[
                    (topo.links.kind == "access")
                    & (topo.links.endpoint_a.isin(chosen))
                    & (topo.links.media == "microwave")
                ]
                si.affected_link_ids = acc.link_id.tolist()
            si.root_entity = ";".join(sorted(chosen))
            si.root_entity_type = "site"
    return si


def schedule_incidents(cfg: GenConfig, topo: Topology, ts_index: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed + 9973)
    start0 = ts_index[0]
    run_end = ts_index[-1]
    out: list[ScheduledIncident] = []

    for i, spec in enumerate(cfg.incidents):
        start = start0 + pd.Timedelta(hours=spec.start_offset_hours)
        end = start + pd.Timedelta(hours=spec.duration_hours)
        if start >= run_end:
            continue
        end = min(end, run_end)
        out.append(_materialise(topo, rng, f"INC{i+1:03d}", spec, start, end, auto=False))

    # auto incidents
    weeks = cfg.duration_days / 7.0
    ai = cfg.auto_incidents
    from networkanalysis.config.models import RAN_KINDS, SHARED_KINDS, TRANSPORT_KINDS

    plan = [
        ("transport", TRANSPORT_KINDS, ai.transport_per_week),
        ("ran", RAN_KINDS, ai.ran_per_week),
        ("shared", SHARED_KINDS, ai.shared_per_week),
    ]
    counter = len(out)
    for cls, kinds, rate in plan:
        k = rng.poisson(rate * weeks)
        for _ in range(int(k)):
            kind = str(rng.choice(kinds))
            dur = float(np.clip(ai.duration_hours.sample(rng), 0.5, 72))
            mag = float(np.clip(ai.magnitude.sample(rng), 0.1, 0.98))
            if cls == "transport":
                n_t = int(np.clip(ai.transport_targets.sample(rng), 1, 40))
            else:
                n_t = int(rng.integers(1, 4))
            offset_h = float(rng.uniform(0, max(cfg.duration_days * 24 - dur, 1)))
            spec = IncidentSpec(
                **{"class": cls}, kind=kind, n_targets=n_t,
                start_offset_hours=offset_h, duration_hours=dur, magnitude=mag,
            )
            start = start0 + pd.Timedelta(hours=offset_h)
            end = min(start + pd.Timedelta(hours=dur), run_end)
            counter += 1
            out.append(_materialise(topo, rng, f"INC{counter:03d}", spec, start, end, auto=True))

    rows = [si.to_row() for si in out]
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "incident_id", "incident_class", "kind", "start_ts", "end_ts", "magnitude",
                "root_entity", "root_entity_type", "n_affected_sites", "affected_site_ids",
                "affected_link_ids", "affected_sectors", "auto_generated",
            ]
        )
    return df.sort_values("start_ts").reset_index(drop=True)
