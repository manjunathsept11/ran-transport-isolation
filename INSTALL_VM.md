# Install & run on a VM

Repo: **https://github.com/manjunathsept11/ran-transport-isolation**

Two ways to run it:

- **[Option A — Docker](#option-a--docker-simplest)** (one command, no toolchain to install)
- **[Option B — native](#option-b--native-python--node)** (uv + Node, better for development)

**VM sizing:** 2 vCPU / 4 GB RAM / 10 GB disk is comfortable. Generation of the default
`mixed_realistic` (300 sites × 14 days) peaks around ~2 GB RAM and takes ~5 min; analytics
another ~7 min. Use fewer sites/days for a smaller box (see [scaling](#scaling)).

Assumes **Ubuntu 22.04 / 24.04** (Debian is the same). Adjust `apt` for other distros.

---

## 0. Clone

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/manjunathsept11/ran-transport-isolation.git
cd ran-transport-isolation
```

---

## Option A — Docker (simplest)

### A.1 Install Docker

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker      # so you can run docker without sudo
```

### A.2 Build & start

```bash
docker compose up -d --build          # builds the React app + the Python image; ~3-5 min first time
docker compose ps
```

This starts two containers:

| Service | Port | What |
|---|---|---|
| `app` | 8000 | FastAPI + the built dashboard |
| `jupyter` | 8888 | JupyterLab on the notebooks (token disabled) |

Data and reports persist in named volumes (`na_data`, `na_reports`).

### A.3 Generate the first dataset

The warehouse starts empty. Either use the dashboard's **Data Generation** page, or from the CLI:

```bash
docker compose exec app na generate --preset mixed_realistic --sites 200 --days 10
docker compose exec app na analytics
docker compose exec app na report
```

(Use `--preset healthy_week --sites 60 --days 2` for a ~30 s smoke run.)

### A.4 Open it

- Dashboard / API: `http://<VM-IP>:8000`
- JupyterLab: `http://<VM-IP>:8888`

If the VM has no public IP, tunnel from your laptop:

```bash
ssh -L 8000:localhost:8000 -L 8888:localhost:8888 user@<VM-IP>
# then open http://localhost:8000
```

Otherwise open the ports in the VM's firewall / cloud security group (8000, and 8888 if you
want notebooks).

### A.5 Manage

```bash
docker compose logs -f app        # follow logs
docker compose restart app        # after pulling new code: docker compose up -d --build
docker compose down               # stop (volumes kept)
docker compose down -v            # stop + wipe data
```

---

## Option B — native (Python + Node)

### B.1 System packages

```bash
sudo apt update
sudo apt install -y git curl build-essential libgomp1
# libgomp1 = OpenMP runtime, needed by lightgbm
```

### B.2 Python via uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env          # or: export PATH="$HOME/.local/bin:$PATH"
uv --version
```

### B.3 Node 20 (for building the dashboard)

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version    # v20.x
```

### B.4 Install the project

```bash
cd ran-transport-isolation
uv venv --python 3.12
uv pip install -e ".[dev]"           # ~2-3 min (pandas, scikit-learn, lightgbm, shap, statsmodels, ruptures, fastapi …)

cd web && npm install && npm run build && cd ..
```

### B.5 Generate → analyse → report

```bash
uv run na generate --preset mixed_realistic --sites 200 --days 10   # ~2 min
uv run na analytics                                                  # ~4 min
uv run na report
uv run na counts                                                     # sanity: warehouse row counts
```

Fast smoke test: `uv run na generate --preset healthy_week --sites 60 --days 2 && uv run na analytics`.

### B.6 Serve

```bash
uv run na serve --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required so the VM accepts connections from outside. Open
`http://<VM-IP>:8000` (or SSH-tunnel as in A.4). The same server serves the API **and** the
built dashboard from `web/dist`.

### B.7 Notebooks (optional)

```bash
uv run jupyter lab --ip 0.0.0.0 --port 8888 --no-browser
```

Open the printed URL (with token). Notebook `00`–`07` under `notebooks/` read the same
`data/warehouse.db`.

### B.8 Keep it running (systemd)

```bash
sudo tee /etc/systemd/system/ran-transport.service > /dev/null <<EOF
[Unit]
Description=RAN & Transport Isolation dashboard
After=network.target

[Service]
User=$USER
WorkingDirectory=$HOME/ran-transport-isolation
ExecStart=$HOME/ran-transport-isolation/.venv/bin/python -m uvicorn networkanalysis.api.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
Environment=PYTHONUTF8=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ran-transport
sudo systemctl status ran-transport
```

---

## Updating to a new version

```bash
cd ran-transport-isolation
git pull

# Docker:
docker compose up -d --build

# native:
uv pip install -e ".[dev]"
cd web && npm install && npm run build && cd ..
sudo systemctl restart ran-transport     # if using the service
```

Your `data/warehouse.db` survives an update (only the schema/data tables are rebuilt on the
next `na generate`; the `job` history is preserved).

---

## Scaling

| Setting | Effect | Small VM (2 GB) | Full demo |
|---|---|---|---|
| `--sites` | linear on generation, ~linear on analytics | 60–150 | 300–400 |
| `--days` | linear on generation | 2–7 | 14 |
| `--load-bin-facts` | also loads the 5-min facts into SQLite (large) | off | off unless you need SQL drill-down |

The 5-min raw feeds always land as parquet under `data/raw/` regardless; the dashboard and
analytics read the hourly rollups.

---

## Verify the install

```bash
uv run pytest -q            # 11 tests, ~2 min (regenerates a tiny dataset)
uv run na verify           # generator determinism + ground-truth-recovery targets, ~4 min
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OSError: libgomp.so.1: cannot open shared object file` | `sudo apt install -y libgomp1` (native) — already in the Docker image |
| Dashboard loads but every page says "no data" | run `na generate` then `na analytics` (or use the Data Generation page) |
| Progress bar stuck / 404 on `/api/jobs/...` | you're on an old build — `git pull` and rebuild; the fix keeps the `job` table across a regenerate |
| `na serve` works locally but not from your laptop | use `--host 0.0.0.0` and open the port (firewall / security group), or SSH-tunnel |
| Generation killed / OOM | fewer `--sites` / `--days`, or give the VM more RAM |
| `npm run build` fails on an old Node | need Node ≥ 18; install Node 20 as in B.3 |
| matplotlib complains about a display | it doesn't — the report forces the headless `Agg` backend |
| Port 8000 in use | `na serve --port 8080` (and adjust the tunnel / firewall) |

---

## What's in the box

`README.md` · `DASHBOARD_GUIDE.md` (how to read every screen) · `METHODS.md` (the
statistical/ML techniques) · `DATA_GENERATION.md` (the generation pipeline + full column
schema). CLI: `na generate` · `na analytics` · `na report` · `na serve` · `na verify` ·
`na counts` · `na presets`.
