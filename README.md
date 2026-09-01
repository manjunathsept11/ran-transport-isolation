# RAN & Transport Isolation Module

Synthetic-data-driven analytics that rank the cell sites / nodes / transport paths most
impacted by **transport-network** problems (vs RAN problems), and hand technicians a
prioritized list for a Phase-2 field audit with root-cause indicators.

Feeds modelled: **Ookla SpeedTest**, **N3 probe EDRs**, **YouTube/Audio QoE**, **TWAMP**,
**SevOne** router counters.

## Components

| Layer | What |
|---|---|
| `src/networkanalysis/topology` | seeded synthetic operator market + IP transport graph |
| `src/networkanalysis/generate` | causal metric model, labelled fault injection (ground truth), raw session synthesis, hourly rollups |
| `src/networkanalysis/db` | SQLite warehouse (schema, bulk load, queries) |
| `src/networkanalysis/pipeline` | serving-cell resolution + unified site feature table |
| `src/networkanalysis/analytics` | scoring/ranking, transport-vs-RAN attribution (rules + LightGBM + SHAP), correlation, anomaly detection, variability, root-cause analysis |
| `src/networkanalysis/report` | HTML/PDF analytics report + Phase-2 audit list (xlsx) |
| `src/networkanalysis/api` | FastAPI backend (read APIs + background generation/analytics jobs) |
| `web/` | React + Vite dashboard (technician UI) |
| `notebooks/` | EDA, correlation, anomaly, variability, attribution, RCA walkthroughs |

## Quick start

Deploying on a VM? See **[`INSTALL_VM.md`](INSTALL_VM.md)** (Docker or native, step by step).

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

# generate the default demo dataset, run analytics, build the report
uv run na generate --preset mixed_realistic
uv run na analytics
uv run na report

# serve the API + dashboard
uv run na serve          # http://localhost:8000
cd web && npm install && npm run dev   # http://localhost:5173
```

Use `--preset healthy_week` for a fast (~90s) smoke run.

**New to the dashboard?** Read [`DASHBOARD_GUIDE.md`](DASHBOARD_GUIDE.md) — what every
screen shows, how to read the numbers, and a worked investigation.
For the statistical / ML techniques behind each module, see [`METHODS.md`](METHODS.md).
For how the synthetic data is produced and the full column schema of every table/file,
see [`DATA_GENERATION.md`](DATA_GENERATION.md).

## Presets

`healthy_week` · `monsoon` · `congestion_buildup` · `fiber_cut_cluster` ·
`mixed_realistic` (default). Edit or add presets in `config/presets/*.yaml`, or from the
dashboard **Settings / Data Generation** page.

## Verification

```bash
uv run pytest
uv run na verify        # generator determinism + ground-truth recovery targets
```
