# Dashboard guide — RAN & Transport Isolation

A walkthrough of every screen: what it shows, what the numbers mean, and how to move
from "something is wrong" to "here is the site, the cause, and the action".

Open it with `uv run na serve` → **http://127.0.0.1:8000**.

---

## 1. The idea in one paragraph

End users complain (slow speed tests, video buffering, dropped calls). The question is
**whose problem is it** — the radio (RAN) or the IP transport network (backhaul / routers /
microwave links)? This tool ingests five data feeds, lines them up per **site / cell /
transport-path / hour**, ranks the sites whose experience is worst, and for each one
decides **transport** vs **RAN** vs **shared** — with the evidence shown so a technician can
trust it. The output is a prioritised list of ~75–100 sites to send to a Phase-2 field audit.

### The five feeds

| Feed | Layer it reports on | Key fields |
|---|---|---|
| **Ookla SpeedTest** | user experience + radio | download / upload throughput, loaded latency, RSRP, RSRQ |
| **N3 probe EDRs** | session — the split point | TCP **client** RTT, TCP **server** RTT, TCP fail %, retransmissions, VoNR MOS |
| **YouTube / Audio QoE** | application | video/audio MOS, rebuffer ratio, startup delay |
| **TWAMP** | pure transport (active probes on each link) | one-way / round-trip delay, frame loss, jitter |
| **SevOne** | transport devices | router queue depth, discards, interface utilisation, CRC errors |

### How the isolation actually works

- **TCP client RTT** is measured from the core probe to the handset — it contains **both**
  the radio scheduling delay **and** the whole transport path. **TCP server RTT** is the
  probe to the internet server — it is site-independent and acts as a **control**: if the
  client RTT is up but the server RTT is flat, the problem is on the access/transport side,
  not the internet.
- To split *access/transport* further into *radio* vs *transport*:
  - **Radio-attributed** if RSRP / RSRQ are degraded, or PRB utilisation is near 100 %,
    and there is **no** matching signal on TWAMP / SevOne / per-link delay.
  - **Transport-attributed** if the transport instruments themselves are lit up (TWAMP
    loss/jitter, SevOne queue/CRC, per-link delay/loss) **and** — the strongest tell —
    **other sites on the same shared uplink are degraded in the same window** (a single
    radio fault can't do that; a backhaul fault does it every time).
  - **Shared / ambiguous** if the site simply went unavailable (power, router reload) with
    no isolated radio or transport signature, or the signatures are mixed.

Everything the analytics does is measured against **injected ground truth** — the synthetic
generator plants labelled faults, so every screen can tell you how accurate it is
(precision / recall, "matched" badges). On real data those badges disappear; the ranking
and evidence stay.

---

## 2. Reading the numbers (applies everywhere)

| Term | What it means | How to read it |
|---|---|---|
| **σ (sigma) / robust z** | how far a KPI is from *normal* for that site | `+3σ` = well outside this site's usual range. Normal is the site's own **trailing** median ± inter-decile spread (so an ongoing fault doesn't hide itself), cross-checked against a **peer group** of similar sites (same morphology + load) at the same hour. |
| **Impact score** | severity × sessions impacted × users impacted, blended across the 5 headline KPIs | Relative, not a unit. Used only to **rank**. A score of 30 is worse than 15; the absolute value isn't meaningful on its own. |
| **Headline KPIs** | TCP client RTT, TCP fail %, Ookla DL throughput, VoNR MOS, YouTube QoE | The five the module ranks on (from the use-case brief). |
| **Attributed cause** | `transport` / `ran` / `shared` / `none` | `none` = the site is degraded but no clean infrastructure signature — keep watching, don't dispatch. |
| **Confidence** | 0–1, isotonic-calibrated | ≥ 0.8 act on it; 0.5–0.8 corroborate on the Transport Paths / Site Detail pages first; < 0.5 treat as a hint. |
| **Worst window** | the 6-hour span with the largest summed KPI degradation | The period to look at on the time-series charts; anomaly markers cluster here. |
| **Priority / "is_priority"** | top slice by impact (≈ top 75–120) | This is the Phase-2 audit list. |

### Colour legend (used on every screen)

| Colour | Meaning |
|---|---|
| 🟠 orange | transport-attributed |
| 🔵 blue | RAN-attributed |
| 🟣 purple | shared / ambiguous |
| ⚪ grey | healthy / no clear cause |

---

## 3. The screens

### 3.1 Market Overview  (`/`)

**Purpose:** the 10-second health read for the whole market.

- **KPI tiles** — priority-site count; transport-attributed count (with RAN / shared
  underneath); current TCP client RTT and YouTube QoE vs the run's opening baseline
  (green = fine, red = degraded).
- **Site map** — every site plotted geographically, coloured by attributed cause; priority
  sites are larger dots. Clusters of orange = a transport problem hitting a whole area
  (e.g. a fibre span or a wet-weather microwave region). **Click a dot → Site Detail.**
- **Priority sites by attributed cause** — the split of the audit list. Mostly orange means
  transport is the dominant driver of poor experience this period.
- **Sessions / users impacted** — modelled totals across the priority sites (synthetic
  counts, not real subscriber identities).
- **Market KPI trend** — market-average TCP RTT / DL throughput / YouTube MOS over the run.
  You should see a clean daily rhythm (evening busy-hour peaks); a sustained shift or a
  step-change is a market-wide event.

**How to use it:** glance at the tiles → look at the map for clustering → jump to Priority
Sites.

---

### 3.2 Priority Sites  (`/priority`)

**Purpose:** the ranked audit list — the main deliverable.

Columns: **rank · site · region · morphology · impact (bar) · cause · confidence ·
headline severity (5 heat cells: RTT / Fail / Thr / VoNR / YT) · sessions impacted ·
worst window.**

- The **heat cells** show which KPIs are driving each site's score — a site red on `RTT`
  and `Thr` but not `VoNR` is a throughput/latency story, not a voice story.
- **Filters:** by attributed cause and by region.
- **Sort:** click any column header.
- **Audit list (xlsx)** — downloads the full ranked list plus per-site evidence and
  recommended actions, ready to hand to the field team. (Also written to
  `reports/phase2_audit_list.xlsx`.)

**Click any row → Site Detail.**

---

### 3.3 Site Detail  (`/sites/<id>`)

**Purpose:** everything about one site — is it really transport, and what do we tell the
technician?

- **Header** — site id, attributed cause tag, region / morphology / backhaul type, rank,
  impact score, and the **attribution confidence** with the rule-engine verdict and the
  ML-model verdict shown separately (they usually agree; when they don't, confidence drops).
- **Why this attribution**
  - *Rule evidence* — plain-English bullets: "RSRP −3.2σ below baseline", "TWAMP frame
    loss +4.1σ", "83 % of sibling sites on the shared uplink also transport-degraded", etc.
  - *Top model features (SHAP)* — which inputs pushed the ML model toward its call, as
    horizontal bars. A transport call driven by `twamp_loss_pct` and `sevone_queue_depth`
    is well-grounded; one driven only by `tcp_client_rtt_ms` is weaker (that KPI is
    ambiguous — radio drives it too).
- **Radio panel vs Transport-path panel** (side by side) — the core comparison. Radio =
  RSRP / RSRQ / PRB utilisation. Transport = path delay / TWAMP loss / SevOne queue.
  Dashed red lines mark detected anomaly peaks. If the transport panel spikes in the worst
  window and the radio panel is flat → transport. Vice-versa → RAN.
- **End-user experience** — TCP **client** RTT vs TCP **server** RTT (the control, should
  stay flat), DL throughput, YouTube MOS. Client RTT climbing while server RTT is flat is
  the signature of an access/transport problem.
- **Transport path topology** — `site → access link → pre-agg router → agg router → core`,
  with each link's media and capacity. This is the chain a transport fault lives on.
- **RCA** — the candidate cause(s), confidence, and the **recommended action** (e.g.
  "check microwave hop R12–R13 alignment / rain-fade margin", "replace the SFP on R13
  port 1/2", "backhaul saturated at busy hour — schedule a capacity upgrade").
- **Anomalies & variability** — the site's anomaly events and its stability rank
  (flagged if variance is high but the mean is acceptable — the fingerprint of an
  *intermittent* transport fault like microwave fade).
- **Ground truth (demo mode)** — the actual injected fault(s), so you can see whether the
  attribution was right. This block is absent on real data.
- **Correlated KPI pairs** — which KPIs move together at this site, and the best time lag
  (e.g. SevOne queue buildup leading the YouTube-MOS drop by ~30 min).

---

### 3.4 Transport Paths & Links  (`/transport`)

**Purpose:** confirm a *common cause* — is one link degrading a whole cluster of sites?

- **Left:** shared transport links (pre-agg and agg uplinks) ranked by worst observed
  frame loss. Columns: link, kind, media (fiber / microwave), sites carried, utilisation %,
  loss %.
- **Right (click a link):** the link's utilisation / loss / jitter over time, and the
  **sibling sites** riding on it — each with its own attributed cause and impact score.
  The line at the bottom — *"N of M sibling sites are transport-attributed"* — is the
  common-cause test: a high fraction means the fault is on this link, not in the individual
  radios.

**How to use it:** from a transport-attributed site on Site Detail, note its pre-agg
uplink, find it here, and check whether its siblings are lit up. If they are, the audit
target is the **link**, not each site.

---

### 3.5 Incidents / RCA  (`/incidents`)

**Purpose:** the network-event view — anomalies grouped into incidents, each with a
root-cause hypothesis.

- **Stat tiles** — detected incidents; how many matched ground truth; RCA hypotheses;
  how many localised to a transport link.
- **Root-cause hypotheses** — cards, most severe first. Each shows the candidate cause
  ("shared transport fault localised to 1 link(s)"), the **entity** (the specific
  link(s), from a minimal-hitting-set search over the topology graph), confidence, a
  **matched-ground-truth badge** in demo mode, the evidence ("19 sites degraded
  concurrently", "minimal hitting set explains 100 % of affected sites", the time window),
  and the recommended action.
- **Detected incidents** — every anomaly cluster: window, predicted class, site count,
  severity, and **IoU** (overlap with the true incident's site set — > 0.2 is a match).
- **Ground truth incidents** — the injected faults; `*` marks an auto-generated background
  incident. Absent on real data.

---

### 3.6 Anomaly Explorer  (`/anomalies`)

**Purpose:** see *when* and *where* things went abnormal, independent of the ranking.

- **Site × time heatmap** — the 40 sites with the most anomaly events; brighter = more
  severe. Vertical bands = a time window that hit many sites at once (an incident).
  Horizontal streaks = one site that was unstable for a long time.
- **Recent anomaly events** — site, KPI, start time, peak severity (σ), and the method
  that caught it (`stl_mad` = seasonal-residual outlier; `iforest_pca` = multivariate
  "many KPIs slightly off"). **Click a row → Site Detail.**

---

### 3.7 Variability  (`/variability`)

**Purpose:** find sites that are *unreliable* even if their average looks OK — classic
intermittent-fault behaviour.

- **Variance decomposition** — of TCP client RTT: how much of the total variation is
  explained by which site you're on vs hour-of-day vs day vs residual.
- **Week-over-week drift** — count of sites whose KPI distribution shifted between the
  first and second half of the run (PSI > 0.2) — a slow degradation, not a spike.
- **Layer driver split** — across priority sites, the median share of YouTube-QoE
  variance attributable to transport features vs radio features. A high transport share
  is corroborating evidence that transport is the market's main lever right now.
- **Least stable sites** — ranked by coefficient of variation *relative to peers with a
  similar mean*. Columns: CV, busy/off-peak ratio, day-to-day variance, WoW-drift flag,
  and an instability tag. These are strong candidates for a microwave-fade or a flapping-
  link audit even if they never top the impact ranking.

---

### 3.8 Data Generation  (`/settings`)

**Purpose:** create the dataset the rest of the dashboard analyses. (On real data this is
where an ingestion config would live; here it drives the synthetic generator.)

- **Preset** — pick a scenario: `healthy_week`, `monsoon` (microwave degradation),
  `congestion_buildup` (slow backhaul saturation), `fiber_cut_cluster` (one link, whole
  cluster), `mixed_realistic` (the default blend). The description explains each.
- **Run** — random seed (same seed ⇒ identical dataset), duration in days, bin size.
- **Market** — number of sites, regions, fraction on microwave backhaul.
- **Metric baselines** — the centre of each KPI's distribution (RSRP, RSRQ, server RTT,
  link delay/loss, site busy-hour load). Nudging these shifts what "normal" looks like.
- **Injected incidents** — the ground-truth faults. Each row: class (transport / ran /
  shared), kind, how many sites, start offset (hours from day 0), duration, magnitude
  (0–1). Add or remove rows. Below: **auto-incident rates** — Poisson rates for random
  background faults per week, so a run has realistic noise without you listing every one.
- **Generate + analytics** — runs the generator, then the full analytics engine, then
  you can build the report. A live progress bar tracks it; when it finishes it prints the
  transport-attribution F1 vs ground truth. "re-run analytics" and "build report" run
  those steps alone. **Save as preset** stores your config under `config/presets/`.
- **Recent jobs** — history of generate / analytics / report runs and their status.

> Generation of the default `mixed_realistic` at 300 sites / 14 days takes a few minutes;
> analytics another few. Use `healthy_week` at ~60 sites / 2 days for a quick trial.

---

## 4. A typical investigation

1. **Overview** — transport tile is high, the map shows an orange cluster in one region.
2. **Priority Sites** — filter to `transport`; the top rows share a region and a worst
   window. Note site S00082.
3. **Site Detail (S00082)** — transport panel spikes (TWAMP loss +4σ, SevOne queue +3σ),
   radio panel flat, client RTT up while server RTT flat, "91 % of sibling sites also
   transport-degraded". Confidence 0.94. Recommended action: inspect the pre-agg fibre span.
4. **Transport Paths** — find S00082's pre-agg uplink; its siblings are almost all orange
   → the fault is the **link**, not 15 separate sites.
5. **Incidents / RCA** — an incident is already localised to that link with a matched
   ground-truth badge and an evidence list.
6. **Priority Sites → Audit list (xlsx)** — export, hand to the field team with the link
   as the target.

---

## 5. Caveats

- **The data is synthetic.** A layered causal model generates it and plants labelled
  faults so accuracy can be measured; it is not a real network.
- **"Sessions / users impacted"** are modelled counts, not real IMSIs.
- **Transport isolation is strong** (precision ≈ 0.9, recall ≈ 1.0 vs ground truth).
  **RAN and "shared" recall are lower** — a RAN-limited site often sits on a transport
  path whose neighbours are degraded, and some "shared" weather events genuinely have a
  transport signature. Treat a `ran` or `shared` call as needing a look at the Site Detail
  radio panel before dispatch.
- **Impact ranking favours transport** because transport faults hit many sites at once, so
  RAN-only sites may not appear in the top 75. Raise RAN incident magnitude/count on the
  Data Generation page, or reweight `src/networkanalysis/analytics/scoring.py`, if you
  want them surfaced.
- **`none` means "degraded, cause unclear"** — not "healthy". Don't dispatch on it.

---

## 6. Where things live

| | |
|---|---|
| Warehouse | `data/warehouse.db` (SQLite) — schema documented in `.claude/skills/network-analysis-context/SKILL.md` |
| 5-min raw feeds | `data/raw/<feed>/dt=YYYY-MM-DD.parquet` (read directly by the notebooks) |
| Report + audit list | `reports/analytics_report.html`, `reports/phase2_audit_list.xlsx` |
| Notebooks | `notebooks/00`–`07` (deeper EDA, correlation, anomaly, attribution, RCA) |
| CLI | `na generate` · `na analytics` · `na report` · `na serve` · `na verify` |
