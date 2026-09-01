"""Build a stable synthetic operator market + IP transport topology.

The topology is seeded separately from the metric generator (``GenConfig.topology_seed``)
so that regenerating metrics does not reshuffle the network. Transport **links are shared**
by clusters of sites: an access link serves one site, a pre-aggregation uplink serves a
whole cluster, an aggregation uplink serves a whole region. That sharing is what makes
transport root-cause localisation meaningful.

Returns a :class:`Topology` bundle of pandas DataFrames, one per dimension table.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from networkanalysis.config.models import MarketConfig

SECTOR_AZIMUTHS = (0, 120, 240)

# band -> (centre freq label, coverage radius km factor, capacity mbps ceiling)
BANDS = {
    "n71": {"ghz": 0.6, "reach": 1.9, "cap": 180.0},
    "n41": {"ghz": 2.5, "reach": 1.0, "cap": 480.0},
    "n77": {"ghz": 3.7, "reach": 0.7, "cap": 950.0},
}

MORPH_BANDPLAN = {
    "dense_urban": ["n71", "n41", "n77"],
    "urban": ["n71", "n41", "n77"],
    "suburban": ["n71", "n41"],
    "rural": ["n71"],
}

MORPH_CELL_RADIUS_KM = {
    "dense_urban": 0.35,
    "urban": 0.8,
    "suburban": 1.6,
    "rural": 4.5,
}


@dataclass
class Topology:
    sites: pd.DataFrame
    cells: pd.DataFrame
    routers: pd.DataFrame
    links: pd.DataFrame
    path_links: pd.DataFrame  # (site_id, hop_index, link_id)
    twamp_sessions: pd.DataFrame
    sevone_interfaces: pd.DataFrame

    @property
    def n_sites(self) -> int:
        return len(self.sites)

    def site_path(self, site_id: str) -> list[str]:
        rows = self.path_links[self.path_links.site_id == site_id].sort_values("hop_index")
        return rows.link_id.tolist()

    def tables(self) -> dict[str, pd.DataFrame]:
        return {
            "dim_site": self.sites,
            "dim_cell": self.cells,
            "dim_router": self.routers,
            "dim_link": self.links,
            "dim_path_link": self.path_links,
            "dim_twamp_session": self.twamp_sessions,
            "dim_sevone_interface": self.sevone_interfaces,
        }


def build_topology(market: MarketConfig, seed: int) -> Topology:
    rng = np.random.default_rng(seed)

    # ---- regions -----------------------------------------------------------
    region_names = list(market.region_mix.keys())[: market.n_regions] or [
        f"R{i+1}" for i in range(market.n_regions)
    ]
    n_regions = len(region_names)
    reg_angles = rng.uniform(0, 2 * np.pi, n_regions)
    reg_r = market.span_deg * 0.32 * np.sqrt(rng.uniform(0, 1, n_regions))
    reg_lat = market.lat_center + reg_r * np.sin(reg_angles)
    reg_lon = market.lon_center + reg_r * np.cos(reg_angles)
    region_weights = np.array([market.region_mix.get(r, 1.0 / n_regions) for r in region_names])
    region_weights = region_weights / region_weights.sum()

    # ---- sites -----------------------------------------------------------
    n = market.n_sites
    site_region_idx = rng.choice(n_regions, size=n, p=region_weights)
    # scatter around region centre; radius drives morphology (closer = denser)
    theta = rng.uniform(0, 2 * np.pi, n)
    rad = np.abs(rng.normal(0, market.span_deg * 0.10, n)) + rng.uniform(0, market.span_deg * 0.02, n)
    site_lat = reg_lat[site_region_idx] + rad * np.sin(theta)
    site_lon = reg_lon[site_region_idx] + rad * np.cos(theta)

    morphs = list(market.morphology_mix.keys())
    morph_w = np.array([market.morphology_mix[m] for m in morphs])
    # bias: inner-radius sites lean dense_urban/urban, outer lean rural
    rad_rank = rad.argsort().argsort() / max(n - 1, 1)  # 0=innermost
    morph_order = ["dense_urban", "urban", "suburban", "rural"]
    site_morph = []
    for i in range(n):
        base = rng.choice(morphs, p=morph_w / morph_w.sum())
        # nudge toward order position by radius
        target = morph_order[min(int(rad_rank[i] * 4), 3)]
        site_morph.append(target if rng.uniform() < 0.55 else base)
    site_morph = np.array(site_morph)

    site_ids = np.array([f"S{idx:05d}" for idx in range(1, n + 1)])
    mw_fraction = market.microwave_fraction
    backhaul = np.where(
        (site_morph == "rural") & (rng.uniform(size=n) < 0.72),
        "microwave",
        np.where(rng.uniform(size=n) < mw_fraction * 0.6, "microwave", "fiber"),
    )
    design_capacity = np.array(
        [BANDS[MORPH_BANDPLAN[m][-1]]["cap"] * rng.uniform(1.4, 2.4) for m in site_morph]
    )

    sites = pd.DataFrame(
        {
            "site_id": site_ids,
            "region": np.array(region_names)[site_region_idx],
            "morphology": site_morph,
            "lat": np.round(site_lat, 6),
            "lon": np.round(site_lon, 6),
            "backhaul_type": backhaul,
            "n_sectors": 3,
            "design_capacity_mbps": np.round(design_capacity, 1),
        }
    )

    # ---- cells ---------------------------------------------------------
    cell_rows = []
    for _, s in sites.iterrows():
        bands = MORPH_BANDPLAN[s.morphology]
        for sec_i, az in enumerate(SECTOR_AZIMUTHS, start=1):
            for band in bands:
                cell_rows.append(
                    {
                        "cell_id": f"{s.site_id}-{sec_i}-{band}",
                        "site_id": s.site_id,
                        "sector": sec_i,
                        "azimuth_deg": az,
                        "band": band,
                        "carrier_ghz": BANDS[band]["ghz"],
                        "cell_radius_km": round(
                            MORPH_CELL_RADIUS_KM[s.morphology] * BANDS[band]["reach"], 3
                        ),
                        "capacity_mbps": round(BANDS[band]["cap"] * float(rng.uniform(0.8, 1.15)), 1),
                    }
                )
    cells = pd.DataFrame(cell_rows)

    # ---- routers -----------------------------------------------------
    router_rows = [{"router_id": "CORE-01", "role": "core", "region": "ALL", "site_count": n}]
    preagg_of_site: dict[str, str] = {}
    agg_of_preagg: dict[str, str] = {}
    for r_i, region in enumerate(region_names, start=1):
        agg_id = f"AGG-{r_i:02d}"
        reg_sites = sites[sites.region == region].site_id.tolist()
        router_rows.append(
            {"router_id": agg_id, "role": "aggregation", "region": region, "site_count": len(reg_sites)}
        )
        # ~18 sites per pre-agg
        n_preagg = max(1, round(len(reg_sites) / 18))
        # order region sites by geography so a pre-agg cluster is spatially coherent
        reg_df = sites[sites.region == region].sort_values(["lon", "lat"])
        chunks = np.array_split(reg_df.site_id.tolist(), n_preagg)
        for p_i, chunk in enumerate(chunks, start=1):
            preagg_id = f"PA-{r_i:02d}-{p_i:02d}"
            agg_of_preagg[preagg_id] = agg_id
            router_rows.append(
                {
                    "router_id": preagg_id,
                    "role": "pre_aggregation",
                    "region": region,
                    "site_count": len(chunk),
                }
            )
            for sid in chunk:
                preagg_of_site[sid] = preagg_id
    routers = pd.DataFrame(router_rows)

    # ---- links + path -------------------------------------------------
    base_cap = 900.0
    link_rows: list[dict] = []
    path_rows: list[dict] = []
    seen_links: set[str] = set()

    def add_link(link_id, a, b, media, kind, capacity):
        if link_id in seen_links:
            return
        seen_links.add(link_id)
        link_rows.append(
            {
                "link_id": link_id,
                "endpoint_a": a,
                "endpoint_b": b,
                "media": media,
                "kind": kind,
                "capacity_mbps": round(capacity, 1),
            }
        )

    # rough peak offered load per site (matches the metric model's demand scale); links
    # are sized to run at a healthy busy-hour utilisation so that *incidents* - not
    # chronic undersizing - are the dominant transport signal.
    per_site_peak = 150.0
    _pa = routers[routers.role == "pre_aggregation"]
    _ag = routers[routers.role == "aggregation"]
    preagg_site_count = dict(zip(_pa.router_id, _pa.site_count))
    region_site_count = dict(zip(_ag.region, _ag.site_count))

    # core uplink per agg
    for r_i, region in enumerate(region_names, start=1):
        agg_id = f"AGG-{r_i:02d}"
        cap = per_site_peak * region_site_count.get(region, 60) / 0.62 * float(rng.uniform(0.95, 1.15))
        add_link(f"L-{agg_id}-CORE", agg_id, "CORE-01", "fiber", "agg_uplink", cap)
    # preagg -> agg
    for preagg_id, agg_id in agg_of_preagg.items():
        media = "microwave" if rng.uniform() < 0.12 else "fiber"
        n_on = preagg_site_count.get(preagg_id, 18)
        cap = per_site_peak * n_on / float(rng.uniform(0.5, 0.68))
        add_link(f"L-{preagg_id}-{agg_id}", preagg_id, agg_id, media, "preagg_uplink", cap)

    for _, s in sites.iterrows():
        preagg_id = preagg_of_site[s.site_id]
        agg_id = agg_of_preagg[preagg_id]
        media = s.backhaul_type
        acc_cap = (base_cap if media == "fiber" else base_cap * 0.42) * float(rng.uniform(0.85, 1.3))
        acc_link = f"L-{s.site_id}-{preagg_id}"
        add_link(acc_link, s.site_id, preagg_id, media, "access", acc_cap)
        path = [
            acc_link,
            f"L-{preagg_id}-{agg_id}",
            f"L-{agg_id}-CORE",
        ]
        for hop_i, lid in enumerate(path):
            path_rows.append({"site_id": s.site_id, "hop_index": hop_i, "link_id": lid})

    links = pd.DataFrame(link_rows)
    path_links = pd.DataFrame(path_rows)

    # ---- TWAMP sessions (one per link) + SevOne interfaces -----------
    twamp = pd.DataFrame(
        {
            "twamp_session_id": "TW-" + links.link_id,
            "link_id": links.link_id,
            "endpoint_a": links.endpoint_a,
            "endpoint_b": links.endpoint_b,
        }
    )
    sevone = pd.DataFrame(
        {
            "sevone_if_id": "IF-" + links.link_id,
            "link_id": links.link_id,
            "router_id": links.endpoint_b,  # upstream router's downstream-facing port
            "if_speed_mbps": links.capacity_mbps,
        }
    )

    return Topology(
        sites=sites,
        cells=cells,
        routers=routers,
        links=links,
        path_links=path_links,
        twamp_sessions=twamp,
        sevone_interfaces=sevone,
    )
