# Methods — statistical / ML / AI techniques used

Everything below is **actually in the code** (not the roadmap). Legend:

- ✅ runs in the main pipeline (`na generate` / `na analytics`)
- 📓 implemented but only wired into a notebook
- ❌ was in the plan, **not built** (listed at the end so expectations are clear)

The app has two distinct halves:

1. a **simulator** that generates the synthetic telecom data — this is physics + parametric
   statistics + a causal model, **not** machine learning;
2. an **analytics engine** that consumes the data — this is where the statistical / ML
   methods live.

There is **no LLM / generative-AI call anywhere in the runtime.**

---

## 1. Synthetic data generation — a physics + statistics simulator

| Method | Purpose | File |
|---|---|---|
| **Structural causal model (SCM)** | layered structural equations `demand → radio → transport → session/app`, all derived from shared latent state so KPI correlations are physical, not bolted-on noise | `generate/model.py` |
| **Parametric probability distributions** | normal, lognormal, beta, gamma, uniform, constant (+ min/max clipping); seeded `numpy` Generator | `config/models.py` (`Distribution`) |
| **M/M/1 queueing approximation** | ρ = offered / capacity; queue occupancy = ρ/(1−ρ); waiting delay ∝ occupancy × service-time → per-link delay / jitter / loss and the SevOne queue / discard counters | `generate/model.py` |
| **Radio link-budget heuristics** | morphology-based path loss → RSRP; offered load → PRB utilisation; interference + load → RSRQ; scheduling delay grows ~cubically as PRB → 100 % | `generate/model.py` |
| **ITU-T G.107 E-model** | R-factor → MOS (1–4.5) for VoNR / packet voice, from one-way delay, jitter and packet loss | `generate/model.py` (`_emodel_mos`) |
| **TCP throughput model** | `min(radio capacity, transport capacity, BDP ÷ RTT-window limit)`; retransmission rate ∝ effective loss | `generate/model.py` |
| **QoE model** | rebuffer ratio = logistic function of throughput deficit + loss; YouTube/audio MOS from rebuffering + latency | `generate/model.py` |
| **Diurnal + weekly seasonality** | 24 hourly multipliers × 7 day-of-week multipliers, smoothly interpolated, applied to demand | `generate/timeprofile.py` |
| **Poisson process** | number of randomly-scheduled background incidents (`rate × weeks`) | `generate/incidents.py` |
| **Fault-signature model** | each incident kind → a vector of state deltas with temporal envelopes: linear onset/offset ramps, `√sin` "weather" envelope, square-wave "flapping", busy-hour weighting | `generate/incidents.py` |
| **Sparse graph aggregation** | `scipy.sparse` site→link incidence matrix; `offered_load_per_link = incidence · offered_load_per_site` | `generate/model.py` |
| **Seeded reproducibility** | separate topology seed vs metric seed; determinism checked by row-count + hash checksum | `verify.py` |

---

## 2. Feature engineering & baselining  ✅

`src/networkanalysis/pipeline/features.py`

- **Robust trailing baseline** — per-site rolling **median** for the centre and a rolling
  **inter-decile range ÷ 2.563** for the scale, both computed on `shift(1)` (past only) so
  an ongoing fault cannot inflate its own "normal" and mask itself.
- **Robust / modified z-score** — `(x − median) / robust_scale`, clipped to ±25.
- **MAD** (median absolute deviation × 1.4826) — fallback robust scale when the IDR is zero.
- **Peer-group normalization** — stratify sites by `morphology × load-band × hour-of-day`
  (load band = tercile of a session-volume rank, `pd.qcut`); z-score each KPI against the
  peer median and peer MAD. Gives `<kpi>__peer_z` alongside the own-baseline `<kpi>__z`.
- **Percentile aggregation** in the hourly rollups — p95 for PRB utilisation, p50 (median)
  for RSRP / RSRQ; RSS combination for path jitter; product rule `1 − Π(1 − lossᵢ)` for
  end-to-end path loss.

---

## 3. Impact scoring & ranking  ✅

`src/networkanalysis/analytics/scoring.py`

- **Per-KPI degradation severity** — session-weighted mean of the positive exceedance of
  the robust-z beyond a threshold (`max(own_z, ½·peer_z) − 2.5`, floored at 0).
- **Multi-criteria weighted composite** — each severity normalised by its 98th percentile,
  then a weighted blend over the five headline KPIs (weights in `DEFAULT_WEIGHTS`).
- **Impact weighting** — `composite × log1p(sessions_impacted) × f(users_impacted)`, where
  the impacted counts come from the fraction of hours the site was degraded.
- **Rolling-window scan** — 6-hour rolling **sum** of summed headline "badness" to locate
  each site's worst window (drives the charts and the attribution time-slice).
- **Priority slice** — top ≈ 9 % of sites (clamped to 75–120) flagged `is_priority`.

---

## 4. Transport-vs-RAN attribution — the core classifier  ✅

`src/networkanalysis/analytics/attribution.py`

| Method | Detail |
|---|---|
| **Deterministic rule engine / expert system** | threshold logic on the robust-z features. Separates **pure-transport** signals (TWAMP loss/jitter, SevOne queue/CRC/util, per-link delay/loss) from **ambiguous** ones (TCP client-RTT, retransmissions — radio drives those too). Emits class + confidence + an ordered plain-English evidence list. Special "clean radio signature, no transport corroboration → RAN" guardrail path. |
| **Sibling-degradation statistic** | for each site, the fraction of *other* sites on the same shared pre-agg uplink that are also transport-degraded in the same window — a spatial-correlation / common-cause feature over the transport graph. |
| **LightGBM** — `LGBMClassifier` | multiclass gradient-boosted decision trees (`transport / ran / shared / none`), `class_weight="balanced"`, ~220 trees, trained on the per-`(site, hour)` feature rows labelled from `dim_incident`. |
| **Isotonic probability calibration** | `sklearn.calibration.CalibratedClassifierCV(method="isotonic", cv=3)` wrapped around the deployment model. |
| **Stratified hold-out** | `train_test_split(test_size=0.25, stratify=y)` — the reported hold-out precision/recall come from this split; a separate calibrated model is refit on all rows for the actual per-site predictions. |
| **SHAP** — `shap.TreeExplainer` | Shapley values on the LightGBM booster; per-site mean \|SHAP\| for the "transport" class → the ranked feature bars shown on the Site Detail page. |
| **Rule + ML ensemble** | agreement → boosted confidence; disagreement → the higher-confidence vote wins, **except** a confident rule "ran" call (clean radio signature) overrides an ML "transport" vote, because the ML over-predicts transport (those hours dominate training). |
| **Window aggregation** | per-`(site, hour)` class probabilities averaged over the site's worst window → one class + confidence per site. |
| **Classification metrics** | precision / recall / F1 (per class + macro), confusion matrix, accuracy — `sklearn.metrics` — reported vs ground truth on the full 300-site set **and** the priority slice. |

---

## 5. Correlation & driver analysis  ✅

`src/networkanalysis/analytics/correlation.py`

- **Spearman rank correlation** — `rank().corr()` on KPI pairs, market-wide and per priority site.
- **Partial correlation** — precision-matrix method: build the rank-correlation matrix,
  invert it (`numpy.linalg.pinv`), and read the normalised negative off-diagonal
  `−P_ij / √(P_ii·P_jj)` → correlation of A and B controlling for the other KPIs.
- **Lead / lag cross-correlation function (CCF)** — Pearson correlation at integer shifts
  from −6 h to +6 h; report the lag with the largest \|corr\|. Surfaces precursors
  (e.g. SevOne queue buildup leading the YouTube-MOS drop by ~30 min).
- **Block-wise OLS R² variance attribution** — ordinary least squares (`numpy.linalg.lstsq`)
  of the ranked target KPI on the **transport feature block** vs the **radio feature block**
  separately; the two R² values, renormalised, give the "layer driver split" (what share
  of a site's QoE variance each layer explains).

---

## 6. Anomaly detection  ✅ (PELT is 📓)

`src/networkanalysis/analytics/anomaly.py`

- **STL decomposition** — `statsmodels.tsa.seasonal.STL(period=24, robust=True)` per
  site × KPI series; anomaly = MAD-scaled robust-z of the **residual** exceeding 3.5σ
  (a seasonal-hybrid-ESD-flavoured univariate detector). Rolling-median residual fallback
  for short / low-variance series.
- **Isolation Forest** — `sklearn.ensemble.IsolationForest` (200 trees, 3 % contamination)
  on the standardised per-`(site, hour)` multivariate feature vector.
- **PCA reconstruction error** — `sklearn.decomposition.PCA` (≤ 6 components); anomaly score
  = RMS reconstruction residual.
- **Multivariate ensemble** — percentile-normalised average of the Isolation-Forest score
  and the PCA reconstruction error; threshold at median + 3·MAD.
- **PELT changepoint detection** 📓 — `ruptures.Pelt(model="rbf")` with an RBF cost and a
  penalty, on standardised KPI series, to bracket incident onset/offset. *Implemented and
  used in notebook `03_anomaly_detection.ipynb`; not called by `run_analytics()`.*
- **Time + topology event clustering** — merge site-level anomalies that overlap in time
  **and** ride the same pre-agg uplink into candidate "incidents"; classify the cluster
  (`transport` if multi-site on a shared link, else `ran`).
- **IoU / Jaccard matching** — detected-incident site set vs ground-truth site set overlap
  `|A∩B| / |A∪B|`; > 0.2 counts as a match for the recovery metrics.

---

## 7. Variability analysis  ✅

`src/networkanalysis/analytics/variability.py`

- **Variance components / one-way ANOVA-style decomposition** — sum-of-squares partition of
  a KPI's total variance into **site**, **hour-of-day**, **day**, and **residual** shares.
- **Coefficient of variation (CV)**, **IQR**, **busy-hour ∶ off-peak ratio** per site.
- **Within-day vs day-to-day variance** — mean of the per-day variances vs the variance of
  the per-day means.
- **Population Stability Index (PSI)** — decile-binned `Σ (aᵢ − eᵢ)·ln(aᵢ/eᵢ)` between the
  first-half and second-half KPI distributions for each site (week-over-week drift; > 0.2
  flags a shift).
- **Peer-relative instability ranking** — rank each site's CV **within its mean-band
  quintile** (`pd.qcut`); the top of that rank with CV > 1.4× median → "high variance,
  acceptable mean" flag (the fingerprint of an intermittent transport fault).

---

## 8. Root-cause analysis / fault localization  ✅

`src/networkanalysis/analytics/rca.py`

- **`networkx` graph model** of the transport topology (sites + routers + links as nodes/edges).
- **Minimal hitting set / greedy set cover** — given the affected-site → candidate-links
  mapping, find the smallest set of shared links that "covers" every affected site — a
  Noisy-OR-style fault-localization heuristic. Reports the coverage fraction as confidence.
- **Signature → fault-kind → action** — a small rule base maps the observed KPI signature
  to a specific fault kind (microwave fade vs congestion vs SFP errors vs …) and a
  recommended technician action.

---

## 9. Data quality / stitching  ✅

`src/networkanalysis/pipeline/stitch.py`

- **Nearest-neighbour serving-cell resolution** — for the fraction of Ookla tests whose
  reported cell id is dropped, resolve the serving site by **Haversine** distance to the
  nearest site, with a margin-based confidence (`gap to 2nd-nearest ÷ distance`). Reports
  the overall match rate and the low-confidence share as a data-quality metric.

---

## 10. Supporting numerics

- **matplotlib** — static chart rendering in the HTML report (not a model).
- **Jinja2** — the analytics report is templated over computed numbers. **No LLM call.**
- **openpyxl / pandas** — the Phase-2 audit list (`.xlsx`).
- **ECharts** (dashboard) — SVG/canvas charts; the site map is a hand-rolled SVG scatter.

---

## Not built (was in the plan `§16`)

Deliberately deferred — the classical stack above was sufficient and keeps the app
explainable and fast to retrain:

| Area | Proposed but not implemented |
|---|---|
| Synthetic calibration | copulas, SDV (CTGAN / TVAE / PAR), TimeGAN, DoppelGANger |
| Forecasting / early warning | Prophet, SARIMA, LightGBM global quantile model, NHITS / PatchTST / TFT, survival analysis |
| Attribution | Explainable Boosting Machine (EBM), automatic rule mining (skope-rules / RIPPER) |
| RCA | Bayesian-network inference (pgmpy), GNN edge classification, causal discovery (PC / NOTEARS) |
| Correlation | Granger causality, transfer entropy, causal forests / double ML (econml) |
| Anomaly | LSTM / USAD / TranAD autoencoders, Matrix Profile (STUMPY), Bayesian online changepoint |
| Variability | DTW time-series clustering, GARCH volatility modelling |
| Scoring | learning-to-rank (LambdaMART), TOPSIS |
| Report | LLM-generated narrative (Claude via the Anthropic API) |
