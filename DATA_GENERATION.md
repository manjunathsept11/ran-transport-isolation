# Data generation & schema reference

How the synthetic dataset is produced, and the **complete column schema** of everything it
writes. Entry point: `na generate` → `src/networkanalysis/generate/runner.py`.

> All data is **synthetic**. It is produced by a seeded, layered causal model with
> deliberately injected, labelled faults — so every analytics result can be scored against
> ground truth. Same `seed` + same config ⇒ byte-identical output.

---

## 1. Pipeline

```
config (GenConfig / preset YAML)
        │
        ▼
1. TOPOLOGY        build_topology()      seeded by  topology_seed
   market → regions → sites → cells;  routers (core / agg / pre-agg);
   links (access / preagg_uplink / agg_uplink);  per-site 3-hop path;
   one TWAMP session + one SevOne interface per link
        │
        ▼
2. INCIDENTS       schedule_incidents()  seeded by  seed + 9973
   explicit incidents from the config  +  Poisson-sampled "auto" incidents;
   each resolved to concrete targets & a time window  →  dim_incident  (GROUND TRUTH)
        │
        ▼
3. METRIC MODEL    run_model()           seeded by  seed
   per 5-min bin, per entity, day by day:
   demand → link queueing → per-site path rollup → radio → session/app KPIs,
   with incident state-deltas injected before KPIs are derived
   →  parquet:  site_bin, link_bin, twamp_5min, sevone_5min, n3_5min
        │
        ▼
4. RAW SESSIONS    generate_sessions()   seeded by  seed + 4242
   Poisson number of individual tests/sessions per site-bin, sampled around the
   bin KPI with per-session noise
   →  parquet:  ookla_test, qoe_session
        │
        ▼
5. ROLLUPS         build_rollups()
   5-min parquet → hourly aggregates;  transport link metrics rolled along each
   site's 3-hop path
   →  agg_site_hourly, agg_link_hourly
        │
        ▼
6. LOAD           reset SQLite → load dimensions, dim_incident, rollups, raw sessions;
                  record the run in gen_run
```

The 5-min bin facts (`fact_site_bin` … `fact_n3_5min`) stay **as parquet only** by default
— the dashboard and analytics read the hourly rollups. `na generate --load-bin-facts`
also loads them into SQLite.

---

## 2. What you configure — `GenConfig`

`src/networkanalysis/config/models.py`; editable from the dashboard **Data Generation** page
or as `config/presets/*.yaml`.

| Field | Default | Meaning |
|---|---|---|
| `name` | `mixed_realistic` | preset name, recorded with the run |
| `seed` | 42 | master RNG seed for metrics + sessions + incidents |
| `topology_seed` | 20240901 | separate seed for the network — regenerating metrics does **not** reshuffle the topology |
| `start_date` | 2026-08-17 | first timestamp |
| `duration_days` | 14 | run length |
| `bin_seconds` | 300 | fact granularity (5 min) |
| `market.n_sites` | 400 | number of cell sites |
| `market.n_regions` | 6 | geographic regions |
| `market.region_mix` | equal | site share per region (normalised) |
| `market.morphology_mix` | `dense_urban .12 / urban .33 / suburban .35 / rural .20` | site type mix |
| `market.microwave_fraction` | 0.28 | share of sites on microwave backhaul |
| `market.lat_center / lon_center / span_deg` | 17.4 / 78.5 / 1.4 | synthetic bounding box (~metro scale) |
| `feeds.ookla.tests_per_site_busy_hour` | Gamma(2.0, 1.3) | Ookla test arrival rate at busy hour |
| `feeds.n3.sampled_flows_per_cell_bin` | Gamma(1.5, 2.0) | N3 individual-flow sampling |
| `feeds.qoe.sessions_per_site_busy_hour` | Gamma(2.5, 2.2) | QoE session arrival rate at busy hour |
| `feeds.qoe.youtube_fraction` | 0.65 | video vs audio split in QoE |
| `metric_baselines` | see below | per-KPI baseline distribution (centre of "normal") |
| `incidents` | preset-specific | explicit labelled faults (list of `IncidentSpec`) |
| `auto_incidents.{transport,ran,shared}_per_week` | preset-specific | Poisson rates for random background faults |

**`metric_baselines`** (each is a `Distribution` = kind + params + optional clip):

| Key | Default distribution | Unit | Drives |
|---|---|---|---|
| `rsrp_dbm` | Normal(μ −95, σ 7) | dBm | per-site RSRP baseline (also shifted by morphology) |
| `rsrq_db` | Normal(μ −11, σ 2.5) | dB | per-site RSRQ baseline |
| `link_base_delay_ms` | Lognormal(median 1.6, σ 0.5), ≥0.2 | ms | per-link fixed propagation/processing delay |
| `link_base_jitter_ms` | Lognormal(median 0.4, σ 0.6), ≥0.02 | ms | per-link base jitter (×1.7 for microwave) |
| `link_base_loss_pct` | Lognormal(median 0.03, σ 0.8), [0, 2] | % | per-link base frame loss (+0.04 for microwave) |
| `link_capacity_mbps` | Lognormal(median 900, σ 0.5), ≥80 | Mbps | reference; actual link caps are sized by cluster in topology |
| `tcp_server_rtt_ms` | Normal(μ 22, σ 4), ≥6 | ms | per-site internet-side RTT (the **control**) |
| `site_busy_hour_erlangs` | Lognormal(median 55, σ 0.55), ≥3 | erlang | per-site busy-hour demand (× morphology scale) |

`Distribution.kind ∈ {normal, lognormal, beta, uniform, gamma, constant}`; `lognormal`
params are on the natural scale (`mean` is the median, `sigma` the log-sd).

---

## 3. Stage 1 — Network topology

`src/networkanalysis/topology/generate.py`. Deterministic given `topology_seed`.

**Regions** — `n_regions` centres scattered inside the market box.
**Sites** — assigned to a region by `region_mix`; scattered around the centre with radius
`|N(0, span·0.10)|`; **morphology** is biased by how central the site is (inner → dense
urban, outer → rural; 55 % snap to the radius-implied type, else drawn from `morphology_mix`).
**Backhaul** — rural sites are 72 % microwave; other sites microwave with probability
`microwave_fraction · 0.6`; otherwise fiber.
**Cells** — 3 sectors (azimuth 0 / 120 / 240°); carriers per morphology:

| Morphology | Bands | Cell radius (km, n71) |
|---|---|---|
| dense_urban | n71, n41, n77 | 0.35 |
| urban | n71, n41, n77 | 0.80 |
| suburban | n71, n41 | 1.60 |
| rural | n71 | 4.50 |

Band reference: `n71` 0.6 GHz / reach ×1.9 / cap 180 Mbps · `n41` 2.5 GHz / ×1.0 / 480 ·
`n77` 3.7 GHz / ×0.7 / 950.

**Routers** — one `CORE-01`; one **aggregation** router per region; one **pre-aggregation**
router per ~18 sites (spatially-coherent clusters).
**Links & the 3-hop path** — every site's traffic flows
`site → [access link] → pre-agg router → [preagg_uplink] → agg router → [agg_uplink] → core`.
Links are **shared**: an access link serves 1 site, a preagg_uplink serves its whole
cluster (~18 sites), an agg_uplink serves the whole region. Capacities are sized so
busy-hour utilisation sits in a healthy band (≈ 0.5–0.75) — so **incidents**, not chronic
undersizing, are the dominant transport signal:

| Link kind | Media | Capacity |
|---|---|---|
| `access` | = site backhaul | `(900 fiber \| 378 microwave) × U(0.85, 1.3)` Mbps |
| `preagg_uplink` | microwave 12 %, else fiber | `150 × (sites on link) ÷ U(0.5, 0.68)` Mbps |
| `agg_uplink` | fiber | `150 × (sites in region) ÷ 0.62 × U(0.95, 1.15)` Mbps |

One **TWAMP session** and one **SevOne interface** are created per link.

### Dimension table schemas

**`dim_site`**

| Column | Type | Unit | How generated |
|---|---|---|---|
| `site_id` | TEXT PK | | `S00001` … |
| `region` | TEXT | | `R1` … `R6` |
| `morphology` | TEXT | | `dense_urban \| urban \| suburban \| rural` |
| `lat`, `lon` | REAL | ° | region centre + scatter |
| `backhaul_type` | TEXT | | `fiber \| microwave` |
| `n_sectors` | INT | | 3 |
| `design_capacity_mbps` | REAL | Mbps | top-band capacity × `U(1.4, 2.4)` |

**`dim_cell`**

| Column | Type | Unit | How generated |
|---|---|---|---|
| `cell_id` | TEXT PK | | `<site>-<sector>-<band>`, e.g. `S00001-1-n41` |
| `site_id` | TEXT FK | | parent site |
| `sector` | INT | | 1 / 2 / 3 |
| `azimuth_deg` | INT | ° | 0 / 120 / 240 |
| `band` | TEXT | | `n71 \| n41 \| n77` |
| `carrier_ghz` | REAL | GHz | 0.6 / 2.5 / 3.7 |
| `cell_radius_km` | REAL | km | morphology radius × band reach |
| `capacity_mbps` | REAL | Mbps | band capacity × `U(0.8, 1.15)` |

**`dim_router`** — `router_id` (PK; `CORE-01`, `AGG-01`, `PA-01-01` …), `role`
(`core \| aggregation \| pre_aggregation`), `region`, `site_count` (sites served).

**`dim_link`** — `link_id` (PK), `endpoint_a`, `endpoint_b`, `media` (`fiber \| microwave`),
`kind` (`access \| preagg_uplink \| agg_uplink`), `capacity_mbps`.

**`dim_path_link`** — `(site_id, hop_index 0..2, link_id)`. `hop_index 0` = access,
`1` = preagg_uplink, `2` = agg_uplink.

**`dim_twamp_session`** — `twamp_session_id` (`TW-<link_id>`), `link_id`, `endpoint_a`, `endpoint_b`.

**`dim_sevone_interface`** — `sevone_if_id` (`IF-<link_id>`), `link_id`, `router_id`
(the upstream router), `if_speed_mbps` (= link capacity).

---

## 4. Stage 2 — Incidents (ground truth)

`src/networkanalysis/generate/incidents.py`. Two sources:

1. **Explicit** — each `IncidentSpec` in the config: `class`, `kind`, `n_targets`,
   `start_offset_hours` (from `start_date`), `duration_hours`, `magnitude` (0–1),
   optional `region` / `morphology` filter.
2. **Auto** — `Poisson(rate_per_week × weeks)` extra incidents per class, with
   magnitude ~ `Beta(2.5, 2.5)`∈[0.15, 0.95], duration ~ `Lognormal(median 5 h, σ 0.7)`,
   transport target count ~ `Gamma(3, 2.5)`∈[1, 40].

**Target resolution** depends on the kind:

- **shared-link transport** (`congested_backhaul`, `fiber_degradation`, `queue_drops`,
  `routing_flap`) → pick `ceil(n_targets/12)` pre-agg uplinks; affected sites = every site
  on them.
- **access-link transport** (`microwave_fade`, `sfp_errors`, `mtu_blackhole`) → pick
  `n_targets` sites (microwave-only for `microwave_fade`); root = their access links.
- **RAN sector** (`sleeping_sector`) → `n_targets` sites, one sector each.
- **other RAN** → `n_targets` sites.
- **shared** — `site_power_outage` / `severe_weather` → sites; `transport_node_reload` →
  a pre-agg router and its downstream sites.

### `dim_incident`

| Column | Type | Meaning |
|---|---|---|
| `incident_id` | TEXT PK | `INC001` … |
| `incident_class` | TEXT | `transport \| ran \| shared` — the label the attribution model is scored against |
| `kind` | TEXT | specific fault (see catalog below) |
| `start_ts`, `end_ts` | TEXT | active window |
| `magnitude` | REAL | 0–1 severity multiplier |
| `root_entity` | TEXT | the faulting entity id(s), `;`-joined (link ids / `site-sector` / site / router) |
| `root_entity_type` | TEXT | `link \| sector \| site \| router` |
| `n_affected_sites` | INT | |
| `affected_site_ids` | TEXT | JSON array |
| `affected_link_ids` | TEXT | JSON array |
| `affected_sectors` | TEXT | JSON array of `"<site>-<sector>"` |
| `auto_generated` | INT | 1 = randomly scheduled background incident |

### Incident catalog & signature

Each kind maps to per-bin **state deltas** (scaled by `magnitude`), applied to the affected
entities during the window with a temporal envelope (linear onset/offset ramp; `weather_like`
adds a `√sin` swell; `flapping` pulses on/off every ~8 min; `busy_hour_weighted` scales with
the diurnal load).

| Kind | Class | Signature (state deltas) |
|---|---|---|
| `microwave_fade` | transport | link loss +3.5, jitter +9 ms, delay +4 ms, capacity ×(1−0.45), CRC ↑; weather envelope |
| `congested_backhaul` | transport | capacity ×(1−0.5), queue +0.55, loss +1.2, jitter +6 ms, delay +12 ms; busy-hour weighted |
| `fiber_degradation` | transport | loss +5.5, delay +6 ms, jitter +4 ms, capacity ×(1−0.7), CRC ↑↑, retrans +6 |
| `sfp_errors` | transport | CRC ↑↑↑, loss +1.8, retrans +5, jitter +2.5 ms; flapping |
| `queue_drops` | transport | queue +0.6, discards +0.05, loss +2.0, jitter +5 ms, delay +8 ms; busy-hour weighted |
| `routing_flap` | transport | delay +25 ms, loss +4.0, jitter +14 ms, TCP fail +3; flapping |
| `mtu_blackhole` | transport | TCP fail +9, retrans +8, loss +0.8, capacity ×(1−0.35) |
| `sleeping_sector` | ran | radio capacity ×(1−0.9), RSRP −14 dB, one sector out of service |
| `external_interference` | ran | RSRQ −7.5 dB, radio capacity ×(1−0.4), retrans +3; busy-hour weighted |
| `coverage_hole` | ran | RSRP −11 dB, radio capacity ×(1−0.3) |
| `cell_overshoot` | ran | RSRQ −5 dB, radio capacity ×(1−0.2) |
| `prb_exhaustion` | ran | PRB utilisation +45 pts, radio capacity ×(1−0.55); busy-hour weighted |
| `vswr` | ran | radio capacity ×(1−0.35), RSRP −4 dB, retrans +2 |
| `site_power_outage` | shared | availability → 0 (all feeds drop for the site) |
| `severe_weather` | shared | link loss +2.5, jitter +6 ms, RSRP −3 dB, capacity ×(1−0.3); weather envelope |
| `transport_node_reload` | shared | availability → 0 + loss spike +8; flapping (short, sharp) |

---

## 5. Stage 3 — Causal metric model

`src/networkanalysis/generate/model.py`. Runs day-by-day; for each 5-min bin it computes,
in order:

**Static per-site draws** (once): `busy_hour_erlangs` = baseline × morphology scale
(`dense_urban 1.8 / urban 1.25 / suburban 0.8 / rural 0.45`); `rsrp_base` =
`{du −88, u −94, sub −98, rural −104} + N(0,3)`; `rsrq_base` = baseline; `radio_capacity` =
`design_capacity × U(0.75, 1.0)`; `server_rtt` = baseline.
**Static per-link draws** (once): `base_delay`, `base_jitter`, `base_loss` from the
baseline distributions (microwave: jitter ×1.7, loss +0.04); `service_ms = 8000 / capacity`.

Then per bin (`shape` = diurnal load multiplier at that timestamp):

```
# demand
site_offered   = busy_hour_erlangs · shape · Lognorm(0,0.10) · 2.3 · site_avail        [Mbps]

# link queueing  (per link; incident deltas d_* already applied)
link_offered   = Σ site_offered over sites whose path includes this link
rho            = clip(link_offered / (capacity · link_cap_mult), 0, 0.999)
queue_occ      = clip(rho/(1−rho)/25 + d_queue, 0, 4)
link_delay     = base_delay + queue_occ · service_ms · 6 + d_delay
link_jitter    = base_jitter · (1 + 1.5·rho) + d_jitter + |N(0,0.15)|
link_loss      = clip(base_loss + clip((rho−0.9)·12, 0)^1.5 + d_loss, 0, 100)          [%]
link_util      = clip(rho·100 + N(0,1.5), 0, 100)
link_discards  = (d_discard + clip(rho−0.92, 0)·0.02) · link_offered
link_crc       = (d_crc + [microwave 0.02 | fiber 0.005]) · (1 + U(0,0.3))

# per-site transport path  (sum/RSS/product over the 3 hops)
path_delay     = Σ link_delay
path_jitter    = √ Σ link_jitter²
path_loss      = (1 − Π(1 − link_loss/100)) · 100                                       [%]
path_capacity  = min link (capacity · link_cap_mult)
avail          = min(site_avail, min link_avail)

# radio
rsrp           = rsrp_base + d_rsrp + N(0,1)                                            [dBm]
rho_site       = clip(site_offered / radio_capacity, 0, 1.3)
prb_util       = clip(rho_site·78 + d_prb + N(0,2.5), 0, 100)                           [%]
rsrq           = rsrq_base + d_rsrq − clip(prb_util−60, 0)·0.05 + N(0,0.6)              [dB]
sched_delay    = 2 + 30·clip(prb_util/100,0,1)³ + clip(−(rsrp+110)/8, 0)                [ms]
radio_capacity_eff = radio_capacity · radio_cap_mult
                 · clip(1−(prb_util−55)/90, 0.08, 1) · clip(1+(rsrq+12)/20, 0.25, 1.15)

# session / app
server_rtt     = server_rtt_base + N(0,1.2)                                            [ms]  (site-independent CONTROL)
client_rtt     = clip(sched_delay + 2·path_delay + N(0,2), 3, ∞)                       [ms]  (radio + full transport, round trip)
radio_bler     = clip((−rsrq−8)·0.4, 0) + clip(prb_util−92, 0)·0.05
eff_loss       = clip(path_loss + radio_bler·0.3, 0, 100)
retrans_pct    = clip(0.4 + 0.9·eff_loss + d_retrans + |N(0,0.15)|, 0, 100)            [%]
tcp_fail_pct   = clip(0.3 + 0.25·eff_loss + clip(client_rtt−120,0)·0.01
                      + d_tcp_fail + clip(prb_util−96,0)·0.2, 0, 100)                   [%]
bdp_limit      = 210 · (35 / clip(client_rtt+server_rtt, 8)) · clip(1−retrans/130, 0.1, 1)
dl_throughput  = clip(min(radio_capacity_eff, path_capacity, bdp_limit)·avail, 0.02)
                 · (0.6 + 0.4/(1+e^((prb_util−95)/3)))                                 [Mbps]
ul_throughput  = dl · 0.13 · clip(1 − radio_bler/30, 0.3, 1)                           [Mbps]
loaded_latency = client_rtt + server_rtt + clip(rho_site·40, 0, 300)                   [ms]
vonr_mos       = E-model(one_way = path_delay + sched_delay/2, eff_loss, path_jitter)  [1–4.5]   (1 if avail<0.5)
deficit        = clip(3.2 − dl, 0) / 3.2
rebuffer_ratio = clip( logistic(deficit·6 + eff_loss·0.2 − 2), 0, 1 ) · [deficit>0]
youtube_qoe_mos= clip(4.6 − 3.2·rebuffer − 0.02·clip(loaded_latency−60,0)/10, 1, 5)    [1–5]     (1 if avail<0.5)

# volumes
users          = clip(busy_hour_erlangs · shape · 3 · Lognorm(0,0.10), 0) · avail
sessions       = users · U(2.5, 4.0)
```

### 5-min parquet outputs

**`fact_site_bin`** — one row per `(site_id, 5-min ts)`

| Column | Unit | = |
|---|---|---|
| `ts`, `site_id` | | keys |
| `offered_mbps` | Mbps | `site_offered` |
| `prb_util_pct` | % | `prb_util` |
| `rsrp_dbm`, `rsrq_db` | dBm / dB | radio quality |
| `sched_delay_ms` | ms | radio scheduling delay |
| `path_delay_ms`, `path_jitter_ms`, `path_loss_pct` | ms / ms / % | transport path, rolled over 3 hops |
| `path_capacity_mbps` | Mbps | min link capacity on the path |
| `radio_capacity_mbps` | Mbps | `radio_capacity_eff` |
| `tcp_client_rtt_ms`, `tcp_server_rtt_ms` | ms | the isolation split |
| `tcp_fail_pct`, `retrans_pct` | % | TCP health |
| `vonr_mos` | 1–4.5 | voice MOS (E-model) |
| `dl_throughput_mbps`, `ul_throughput_mbps` | Mbps | |
| `loaded_latency_ms` | ms | latency under load (bufferbloat) |
| `youtube_qoe_mos` | 1–5 | video MOS |
| `rebuffer_ratio` | 0–1 | fraction of playback stalled |
| `sessions`, `users` | count | volume in the bin |
| `availability` | 0–1 | 0 during an outage |

**`fact_link_bin`** — one row per `(link_id, 5-min ts)`: `offered_mbps`, `util_pct` (%),
`queue_occ` (0–4 normalised), `delay_ms`, `jitter_ms`, `loss_pct` (%), `discards_pps`,
`crc_rate`, `availability`.

**`fact_twamp_5min`** — one row per `(link_id, 5-min ts)`, the active-probe view of the
link: `rtt_ms` = `2·link_delay`, `owd_ms` = `link_delay`, `jitter_ms` = `link_jitter`,
`frame_loss_pct` = `link_loss`.

**`fact_sevone_5min`** — one row per `(link_id, 5-min ts)`, the device-counter view:
`in_util_pct` = `link_util`, `out_util_pct` = `link_util·0.85`, `queue_depth` =
`queue_occ·100`, `discards` = `link_discards·300`, `crc_errors` = `link_crc·1000`,
`if_errors` = `link_crc·400`.

**`fact_n3_5min`** — one row per `(site_id, 5-min ts)`, the probe EDR aggregate:
`tcp_client_rtt_ms`, `tcp_server_rtt_ms`, `tcp_fail_pct`, `retrans_pct`, `vonr_mos`
(same values as `fact_site_bin`), `flow_count` = `sessions`, `user_count` = `users`.

---

## 6. Stage 4 — Raw session records

`src/networkanalysis/generate/sessions.py`. For each site-bin, draw a **Poisson** count of
sessions (`rate · load_ratio · availability`, where `load_ratio` = the bin's offered load
÷ that site's mean), then expand to individual rows with per-session noise around the bin
KPI.

**`fact_ookla_test`** — one row per SpeedTest

| Column | Type | Unit | = |
|---|---|---|---|
| `test_id` | TEXT PK | | `OK<day><...>` |
| `ts` | TEXT | | bin ts + `U(0, 300 s)` |
| `site_id` | TEXT | | true serving site |
| `cell_id` | TEXT | | site's primary (sector-1) cell |
| `lat`, `lon` | REAL | ° | site location + `N(0, 0.004°)` |
| `device_class` | TEXT | | `flagship .34 / midrange .42 / entry .19 / iot .05` |
| `dl_mbps` | REAL | Mbps | bin `dl_throughput · Lognorm(0, 0.22)` |
| `ul_mbps` | REAL | Mbps | bin `ul_throughput · Lognorm(0, 0.25)` |
| `loaded_latency_ms` | REAL | ms | bin `loaded_latency · Lognorm(0, 0.18)` |
| `rsrp_dbm` | REAL | dBm | bin `rsrp + N(0, 2.5)` |
| `rsrq_db` | REAL | dB | bin `rsrq + N(0, 1.2)` |

**`fact_qoe_session`** — one row per YouTube/audio session

| Column | Type | Unit | = |
|---|---|---|---|
| `session_id` | TEXT PK | | `QS<day><...>` |
| `ts` | TEXT | | bin ts + `U(0, 300 s)` |
| `site_id`, `cell_id` | TEXT | | serving site / primary cell |
| `service` | TEXT | | `youtube` (prob `youtube_fraction`) or `audio` |
| `mos` | REAL | 1–5 | bin `youtube_qoe_mos` (or `vonr_mos` for audio) + `N(0, 0.25/0.2)` |
| `rebuffer_ratio` | REAL | 0–1 | bin `rebuffer_ratio · Lognorm(0, 0.4)` |
| `startup_ms` | REAL | ms | `700 + 90·client_rtt/20 + N(0, 250)` |
| `bitrate_kbps` | REAL | kbps | `dl_throughput · 900 · U(0.5, 0.9)` |

---

## 7. Stage 5 — Hourly rollups (what the dashboard reads)

`src/networkanalysis/generate/rollup.py`. 5-min parquet → hourly. Site KPIs are aggregated
(median for RSRP/RSRQ, p95 for PRB, mean for the rest, sum for sessions, min for
availability). The site's transport-path health is built by joining each hop's
`agg_link_hourly` + hourly TWAMP + hourly SevOne and rolling over the 3 hops (sum delay,
RSS jitter, product-rule loss, max on the SevOne/TWAMP counters).

**`agg_site_hourly`** — PK `(site_id, ts_hour)`

| Column | Unit | Source |
|---|---|---|
| `rsrp_p50`, `rsrq_p50` | dBm / dB | hourly median |
| `prb_util_p95` | % | hourly p95 |
| `tcp_client_rtt_ms`, `tcp_server_rtt_ms`, `tcp_fail_pct`, `retrans_pct` | ms / % | hourly mean |
| `vonr_mos`, `dl_throughput_mbps`, `ul_throughput_mbps`, `loaded_latency_ms` | | hourly mean |
| `youtube_qoe_mos`, `rebuffer_ratio` | | hourly mean |
| `path_delay_ms`, `path_jitter_ms`, `path_loss_pct` | ms / ms / % | rolled over the path's links |
| `twamp_rtt_ms`, `twamp_jitter_ms`, `twamp_loss_pct` | ms / ms / % | max over the path's TWAMP sessions |
| `sevone_util_pct`, `sevone_queue_depth`, `sevone_discards`, `sevone_crc` | % / — / — / — | max over the path's SevOne interfaces |
| `sessions` | count | hourly sum |
| `users` | count | hourly mean |
| `availability` | 0–1 | hourly min |

**`agg_link_hourly`** — PK `(link_id, ts_hour)`: `util_pct`, `queue_occ`, `delay_ms`,
`jitter_ms`, `loss_pct`, `discards_pps`, `crc_rate` (hourly mean), `availability` (min).

---

## 8. Analytics-output tables (written by `na analytics`, not by generation)

| Table | Grain | Key columns |
|---|---|---|
| `site_scorecard` | per site | `rank`, `impact_score`, `severity_{tcp_rtt,tcp_fail,throughput,vonr,youtube}`, `sessions_impacted`, `users_impacted`, `worst_window_start/end`, `primary_attribution`, `attribution_confidence`, `is_priority` |
| `impairment_attribution` | per site | `rule_class / rule_confidence / rule_evidence` (JSON), `ml_class / ml_confidence / ml_top_features` (JSON SHAP), `final_class / final_confidence`, `matched_incident_id / matched_incident_class` (ground truth) |
| `anomaly_event` | per event | `entity_type`, `entity_id`, `metric`, `start_ts / end_ts / peak_ts`, `severity` (σ), `method` (`stl_mad` / `iforest_pca`), `direction` |
| `incident_detected` | per cluster | `start_ts / end_ts`, `n_sites / n_links`, `site_ids / link_ids` (JSON), `severity`, `predicted_class`, `confidence`, `matched_incident_id`, `match_iou` |
| `rca_finding` | per site or incident | `scope` (`site`/`incident`), `scope_id`, `candidate_cause`, `candidate_entity`, `cause_class`, `confidence`, `evidence` (JSON), `recommended_action`, `matched_incident_id` |
| `correlation_edge` | per KPI pair | `scope` (`market`/`site`), `scope_id`, `metric_a`, `metric_b`, `spearman`, `partial`, `best_lag_min`, `lag_corr` |
| `variability_site` | per site | `metric`, `cv`, `iqr`, `busy_offpeak_ratio`, `within_day_var`, `day_to_day_var`, `stability_rank`, `instability_flag`, `wow_psi`, `wow_shift` |
| `site_baseline` | per site×metric | `own_median`, `own_mad`, `peer_median`, `peer_mad`, `direction` *(reserved; feature table is built in-memory)* |

## 9. Operational metadata

| Table | Purpose |
|---|---|
| `gen_run` | one row per `na generate`: `run_id`, `preset`, `seed`, `topology_seed`, `start_date`, `duration_days`, `bin_seconds`, `n_sites`, `n_links`, `n_incidents`, `config_json` (the full `GenConfig`), `row_counts_json` |
| `analytics_run` | one row per `na analytics`: `run_id`, `gen_run_id`, `metrics_json` (all accuracy / recall numbers) |
| `job` | background-job state for the dashboard: `kind`, `status`, `progress`, `message`, `params_json`, `result_json` |
| `kv_meta` | `latest_gen_run`, `latest_analytics_run`, `driver_split` |

---

## 10. Raw parquet layout & volumes

```
data/
  raw/
    site_bin/   dt=2026-08-17.parquet …      (n_sites × 288 rows/day)
    link_bin/   dt=…                          (n_links × 288 rows/day)
    twamp_5min/ dt=…                          (n_links × 288)
    sevone_5min/dt=…                          (n_links × 288)
    n3_5min/    dt=…                          (n_sites × 288)
    ookla_test/ dt=…                          (~Poisson, ~15–25 / site / day)
    qoe_session/dt=…                          (~Poisson, ~30–50 / site / day)
  warehouse.db                                 (SQLite: dims + rollups + raw sessions + analytics)
```

Approximate scale for the default `mixed_realistic` at **300 sites / 14 days**:

| Feed | Rows |
|---|---|
| `fact_site_bin` (parquet) | ~1.2 M |
| `fact_link_bin` / `twamp` / `sevone` (parquet) | ~1.3 M each |
| `fact_n3_5min` (parquet) | ~1.2 M |
| `fact_ookla_test` (SQLite) | ~260 k |
| `fact_qoe_session` (SQLite) | ~555 k |
| `agg_site_hourly` (SQLite) | ~100 k |
| `agg_link_hourly` (SQLite) | ~108 k |
| `dim_*` | 300 sites · ~1 900 cells · ~320 links · 24 routers · 15–17 incidents |

Column types in parquet: `ts` = `timestamp[ms]`, ids = string, all metrics = `float32`
(rounded to 4 dp) in the 5-min facts and `float64` in the raw session records.
