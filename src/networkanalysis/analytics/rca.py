"""Root-cause analysis -> rca_finding.

Combines attribution + anomaly clusters + topology into a ranked candidate-cause list per
priority site and per detected incident. Transport localisation is a minimal-hitting-set
over the shared-link -> affected-site mapping (a Noisy-OR style fault model), computed on
the networkx transport graph.
"""

from __future__ import annotations

import json

import networkx as nx
import numpy as np
import pandas as pd

from networkanalysis.db.database import connect

ACTIONS = {
    "microwave_fade": "Check microwave hop link budget / antenna alignment / radome; review ACM state and rain-fade margin.",
    "congested_backhaul": "Backhaul is saturated at busy hour - schedule a capacity upgrade or add a QoS policy; verify no rogue high-volume subscriber.",
    "fiber_degradation": "Dispatch to inspect the fibre span / patch panel on the pre-agg uplink; check optical power (Rx dBm) and for macro-bends or a damaged splice.",
    "sfp_errors": "Replace the suspect SFP/optic on the upstream router port; clean connectors; check for CRC/FCS error counters clearing after swap.",
    "queue_drops": "Egress queue is overflowing - review WRED/queue-limit config and shaper rates on the pre-agg uplink.",
    "routing_flap": "Investigate an unstable IGP/BGP adjacency or a flapping interface on the path; check logs for link up/down events.",
    "mtu_blackhole": "Path MTU black-hole - verify MTU consistency and MSS clamping across the transport path; check for a mis-set jumbo-frame boundary.",
    "sleeping_sector": "Sector carrying ~no traffic - check cell admin/operational state, VSWR alarm, and RF port; may need a site visit or remote reset.",
    "external_interference": "RSRQ degraded with flat transport - run an interference scan / spectrum sweep; look for external emitters or PIM.",
    "coverage_hole": "Persistent low RSRP - review antenna tilt/azimuth and consider a coverage optimisation or small-cell in-fill.",
    "prb_exhaustion": "Cell is PRB-bound at busy hour - carrier add / load-balancing / capacity upgrade.",
    "vswr": "VSWR / feeder fault likely - inspect jumpers, connectors and antenna line; check RET and TMA.",
    "site_power_outage": "Total site outage - verify commercial power / rectifier / battery and generator; raise a power ticket.",
    "severe_weather": "Weather-correlated multi-site degradation (mostly microwave) - monitor; no dispatch unless damage persists after the event.",
    "transport_node_reload": "Upstream router reloaded - confirm it is stable, check for a crash/OOM, and review the change record.",
}


def _transport_graph(db_path=None) -> nx.Graph:
    con = connect(db_path)
    try:
        links = pd.read_sql_query("SELECT * FROM dim_link", con)
        routers = pd.read_sql_query("SELECT * FROM dim_router", con)
        sites = pd.read_sql_query("SELECT site_id FROM dim_site", con)
    finally:
        con.close()
    g = nx.Graph()
    for _, r in routers.iterrows():
        g.add_node(r.router_id, kind="router", role=r.role)
    for s in sites.site_id:
        g.add_node(s, kind="site")
    for _, l in links.iterrows():
        g.add_edge(l.endpoint_a, l.endpoint_b, link_id=l.link_id, kind=l.kind, media=l.media)
    return g


def _minimal_hitting_set(site_to_links: dict[str, list[str]]) -> list[str]:
    """Greedy minimal set of links covering every affected site."""
    uncovered = set(site_to_links)
    chosen: list[str] = []
    link_sites: dict[str, set] = {}
    for s, ls in site_to_links.items():
        for l in ls:
            link_sites.setdefault(l, set()).add(s)
    while uncovered:
        best = max(link_sites, key=lambda l: len(link_sites[l] & uncovered), default=None)
        if best is None or not (link_sites[best] & uncovered):
            break
        chosen.append(best)
        uncovered -= link_sites[best]
    return chosen


def _evidence_for_site(feat_win: pd.DataFrame) -> list[str]:
    ev = []
    checks = [
        ("twamp_loss_pct__z", "TWAMP frame loss", 2.0, 1),
        ("sevone_queue_depth__z", "SevOne queue depth", 2.0, 1),
        ("sevone_crc__z", "SevOne CRC errors", 2.0, 1),
        ("path_delay_ms__z", "path delay", 2.0, 1),
        ("retrans_pct__z", "TCP retransmissions", 2.0, 1),
        ("rsrp_p50__z", "RSRP", 2.5, -1),
        ("rsrq_p50__z", "RSRQ", 2.0, -1),
        ("prb_util_p95__z", "PRB utilisation", 3.0, 1),
    ]
    for col, label, thr, direction in checks:
        if col not in feat_win:
            continue
        v = feat_win[col].mean() * direction
        if v > thr:
            ev.append(f"{label} {feat_win[col].mean():+.1f}σ vs baseline")
    return ev


def build_rca(feat: pd.DataFrame, scorecard: pd.DataFrame, attribution: pd.DataFrame,
              detected: pd.DataFrame, db_path=None) -> pd.DataFrame:
    con = connect(db_path)
    try:
        path_links = pd.read_sql_query(
            "SELECT p.site_id, p.link_id, l.kind, l.media FROM dim_path_link p "
            "JOIN dim_link l ON l.link_id=p.link_id", con
        )
    finally:
        con.close()
    attr = attribution.set_index("site_id")
    sc = scorecard.set_index("site_id")
    findings: list[dict] = []

    # ---- per priority site ----
    for site in scorecard[scorecard.is_priority == 1].site_id:
        if site not in attr.index:
            continue
        row = attr.loc[site]
        w0 = pd.Timestamp(sc.loc[site, "worst_window_start"])
        w1 = pd.Timestamp(sc.loc[site, "worst_window_end"])
        fw = feat[(feat.site_id == site) & (feat.ts_hour >= w0) & (feat.ts_hour <= w1)]
        ev = _evidence_for_site(fw)
        cls = row.final_class

        if cls == "transport":
            up = path_links[(path_links.site_id == site) & (path_links.kind != "agg_uplink")]
            cand_link = up.sort_values("kind").iloc[-1] if len(up) else None
            entity = cand_link.link_id if cand_link is not None else "unknown-link"
            media = cand_link.media if cand_link is not None else "?"
            kind_guess = "microwave_fade" if media == "microwave" else "fiber_degradation"
            # refine kind from signature
            if fw.get("sevone_queue_depth__z", pd.Series([0])).mean() > 2.5:
                kind_guess = "congested_backhaul"
            elif fw.get("sevone_crc__z", pd.Series([0])).mean() > 2.5:
                kind_guess = "sfp_errors"
            action = ACTIONS.get(kind_guess, "Investigate the transport path.")
            cand_name = f"{kind_guess.replace('_', ' ')} on {entity}"
        elif cls == "ran":
            entity = f"{site} radio"
            kg = "prb_exhaustion" if fw.get("prb_util_p95__z", pd.Series([0])).mean() > 3 else (
                "external_interference" if fw.get("rsrq_p50__z", pd.Series([0])).mean() < -2 else "coverage_hole"
            )
            action = ACTIONS.get(kg)
            cand_name = f"{kg.replace('_', ' ')} at {site}"
        elif cls == "shared":
            entity = site
            action = ACTIONS["site_power_outage"]
            cand_name = "site availability event (power / co-located node)"
        else:
            entity = site
            action = "No strong root-cause signature; keep under observation."
            cand_name = "no clear root cause"

        matched = row.get("matched_incident_id")
        findings.append({
            "scope": "site", "scope_id": site,
            "candidate_cause": cand_name, "candidate_entity": entity, "cause_class": cls,
            "confidence": float(row.final_confidence),
            "evidence": json.dumps(ev + json.loads(row.rule_evidence or "[]")[:3]),
            "recommended_action": action,
            "detected_incident_id": None,
            "matched_incident_id": matched if isinstance(matched, str) else None,
        })

    # ---- per detected incident: transport fault localisation ----
    if detected is not None and not detected.empty:
        seen_entities: set[str] = set()
        for i, inc in detected.sort_values("severity", ascending=False).reset_index(drop=True).iterrows():
            sites = json.loads(inc.site_ids or "[]")
            if inc.predicted_class != "transport" or len(sites) < 2:
                continue
            s2l = {
                s: path_links[(path_links.site_id == s) & (path_links.kind != "agg_uplink")].link_id.tolist()
                for s in sites
            }
            hs = _minimal_hitting_set(s2l)
            key = ";".join(sorted(hs))
            if key in seen_entities:   # same link(s) already localised - skip the duplicate
                continue
            seen_entities.add(key)
            cov = sum(any(l in s2l[s] for l in hs) for s in sites) / max(len(sites), 1)
            findings.append({
                "scope": "incident", "scope_id": f"DET{i+1:03d}",
                "candidate_cause": f"shared transport fault localised to {len(hs)} link(s)",
                "candidate_entity": ";".join(hs), "cause_class": "transport",
                "confidence": round(float(np.clip(0.5 + 0.4 * cov, 0.5, 0.95)), 3),
                "evidence": json.dumps([
                    f"{len(sites)} sites degraded concurrently",
                    f"minimal hitting set explains {cov*100:.0f}% of affected sites",
                    f"window {inc.start_ts} .. {inc.end_ts}",
                ]),
                "recommended_action": ACTIONS["fiber_degradation"],
                "detected_incident_id": int(i + 1),
                "matched_incident_id": inc.matched_incident_id,
            })
    return pd.DataFrame(findings)
