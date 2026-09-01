# Install & run on a VM

Repo: **https://github.com/manjunathsept11/ran-transport-isolation**

- **[Windows VM — native](#windows-vm--native)** (recommended for a Windows Server / Win10/11 VM)
- **[Windows VM — Docker Desktop](#windows-vm--docker-desktop)**
- **[Linux VM](#linux-vm)** (Docker or native)

**VM sizing:** 2 vCPU / 4 GB RAM / 10 GB disk is comfortable. Generating the default
`mixed_realistic` (300 sites × 14 days) peaks around ~2 GB RAM and takes ~5 min; analytics
another ~7 min. Use fewer sites/days on a smaller box — see [scaling](#scaling).

---

## Windows VM — native

Tested on Windows 11 / Windows Server 2022. Run the commands in **PowerShell**.

> **You connect over Remote Desktop (RDP)** → just open **`http://localhost:8000`** in the
> VM's own browser (Edge). You can skip the `--host 0.0.0.0` and firewall steps (6) — those
> are only for reaching the dashboard from a *different* machine.

### 1. Install prerequisites

```powershell
# Git, Node 20 LTS, and uv (Python manager). winget ships with Windows 10 21H2+ / Server 2022.
winget install --id Git.Git -e --source winget
winget install --id OpenJS.NodeJS.LTS -e --source winget
winget install --id astral-sh.uv -e --source winget
```

If `winget` is unavailable, install manually:
- Git: <https://git-scm.com/download/win>
- Node 20 LTS: <https://nodejs.org/en/download>
- uv: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

**Close and reopen PowerShell** so the new `PATH` takes effect, then check:

```powershell
git --version ; node --version ; uv --version
```

### 2. Enable long paths + UTF-8 (one time, important)

```powershell
# node_modules / .venv nest deep - Windows' 260-char path limit will otherwise break installs
git config --global core.longpaths true
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
  -Name LongPathsEnabled -Value 1 -PropertyType DWORD -Force | Out-Null

# the CLI progress bar uses Unicode; the legacy console codepage crashes on it
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "Machine")
```

Reopen PowerShell once more so `PYTHONUTF8` is set.

### 3. Clone & install

```powershell
cd $HOME
git clone https://github.com/manjunathsept11/ran-transport-isolation.git
cd ran-transport-isolation

uv venv --python 3.12
uv pip install -e ".[dev]"          # ~2-3 min (pandas, scikit-learn, lightgbm, shap, statsmodels, ruptures, fastapi ...)

cd web
npm install
npm run build
cd ..
```

`uv` downloads its own Python 3.12 — you do **not** need Python pre-installed (avoid the
Microsoft Store Python shim if you have it).

### 4. Generate data → analyse → report

```powershell
uv run na generate --preset mixed_realistic --sites 200 --days 10   # ~2 min
uv run na analytics                                                  # ~4 min
uv run na report
uv run na counts                                                     # sanity check: warehouse row counts
```

Fast smoke test: `uv run na generate --preset healthy_week --sites 60 --days 2 ; uv run na analytics`

### 5. Serve the dashboard

```powershell
uv run na serve --port 8000
```

Then in the VM (over RDP) open **`http://localhost:8000`** in Edge. The one server serves
both the API and the built dashboard.

### 6. (Only to reach it from another machine) — bind wide + open the firewall

Skip this if you use the VM's own browser over RDP.

```powershell
uv run na serve --host 0.0.0.0 --port 8000
New-NetFirewallRule -DisplayName "RAN-Transport 8000" -Direction Inbound `
  -Protocol TCP -LocalPort 8000 -Action Allow
```

Then browse to `http://<VM-IP-or-hostname>:8000` from your laptop.

### 7. Run it as a background service (survives logout / reboot)

Simplest is a **Scheduled Task** that starts at boot:

```powershell
$action  = New-ScheduledTaskAction -Execute "$HOME\ran-transport-isolation\.venv\Scripts\python.exe" `
           -Argument "-m uvicorn networkanalysis.api.main:app --host 0.0.0.0 --port 8000" `
           -WorkingDirectory "$HOME\ran-transport-isolation"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "RAN-Transport-Dashboard" -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings
Start-ScheduledTask -TaskName "RAN-Transport-Dashboard"
```

(Set `PYTHONUTF8=1` at Machine scope as in step 2 so the task inherits it.)
To stop: `Stop-ScheduledTask -TaskName "RAN-Transport-Dashboard"`.
For a more robust Windows service, use [NSSM](https://nssm.cc/) wrapping the same
`python -m uvicorn ...` command.

### 8. Notebooks (optional)

```powershell
uv run jupyter lab --ip 0.0.0.0 --port 8888 --no-browser
```

Open the printed URL (with token). Notebooks `00`-`07` read the same `data\warehouse.db`.

### Updating

```powershell
cd $HOME\ran-transport-isolation
git pull
uv pip install -e ".[dev]"
cd web ; npm install ; npm run build ; cd ..
Restart-ScheduledTask -TaskName "RAN-Transport-Dashboard"   # if using the task
```

Your `data\warehouse.db` survives an update.

---

## Windows VM — Docker Desktop

If the VM can run Docker Desktop (needs virtualization / WSL2 enabled):

```powershell
winget install --id Docker.DockerDesktop -e
# start Docker Desktop once, let it finish setup, then:

cd $HOME\ran-transport-isolation
docker compose up -d --build          # builds web + python image; ~3-5 min first run
docker compose ps
```

| Service | Port | What |
|---|---|---|
| `app` | 8000 | FastAPI + dashboard |
| `jupyter` | 8888 | JupyterLab (token disabled - firewall it) |

Generate the first dataset:

```powershell
docker compose exec app na generate --preset mixed_realistic --sites 200 --days 10
docker compose exec app na analytics
docker compose exec app na report
```

Open `http://<VM-IP>:8000` (open port 8000 in the firewall as in the native step 6).
Manage: `docker compose logs -f app` · `docker compose restart app` · `docker compose down`
(add `-v` to also wipe the data volumes). Update: `git pull ; docker compose up -d --build`.

---

## Linux VM

### Docker (simplest)

```bash
# install Docker
sudo apt update && sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/manjunathsept11/ran-transport-isolation.git
cd ran-transport-isolation
docker compose up -d --build
docker compose exec app na generate --preset mixed_realistic --sites 200 --days 10
docker compose exec app na analytics && docker compose exec app na report
```

Open `http://<VM-IP>:8000` (open the port in the cloud security group, or SSH-tunnel:
`ssh -L 8000:localhost:8000 -L 8888:localhost:8888 user@<VM-IP>`).

### Native

```bash
sudo apt update && sudo apt install -y git curl build-essential libgomp1
curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs

git clone https://github.com/manjunathsept11/ran-transport-isolation.git
cd ran-transport-isolation
uv venv --python 3.12 && uv pip install -e ".[dev]"
cd web && npm install && npm run build && cd ..

uv run na generate --preset mixed_realistic --sites 200 --days 10
uv run na analytics && uv run na report
uv run na serve --host 0.0.0.0 --port 8000
```

systemd unit:

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
sudo systemctl daemon-reload && sudo systemctl enable --now ran-transport
```

---

## Scaling

| Setting | Effect | Small VM (2 GB) | Full demo |
|---|---|---|---|
| `--sites` | ~linear on generation and analytics | 60-150 | 300-400 |
| `--days` | ~linear on generation | 2-7 | 14 |
| `--load-bin-facts` | also loads 5-min facts into SQLite (large) | off | off unless you need SQL drill-down |

The 5-min raw feeds always land as parquet under `data/raw/`; the dashboard and analytics
read the hourly rollups.

---

## Verify the install

```
uv run pytest -q       # 11 tests, ~2 min (regenerates a tiny dataset)
uv run na verify       # generator determinism + ground-truth-recovery targets, ~4 min
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `UnicodeEncodeError: 'charmap' codec ...` when running `na generate` (Windows) | set `PYTHONUTF8=1` (step 2). Per-session: `$env:PYTHONUTF8=1` |
| `npm install` fails with `ENAMETOOLONG` / path errors (Windows) | enable long paths (step 2), then delete `web\node_modules` and retry |
| `OSError: libgomp.so.1: cannot open shared object file` (Linux native) | `sudo apt install -y libgomp1` — already in the Docker image |
| lightgbm import error about a missing DLL (Windows) | install the "Microsoft Visual C++ Redistributable (x64)" from Microsoft, then reopen PowerShell |
| Dashboard loads but every page says "no data" | run `na generate` then `na analytics` (or use the Data Generation page) |
| Progress bar stuck / `/api/jobs/...` 404s | old build - `git pull` + rebuild; the fix keeps the `job` table across a regenerate |
| Works locally, not from another machine | use `--host 0.0.0.0` **and** open port 8000 in the firewall / security group |
| Generation killed / OOM | fewer `--sites` / `--days`, or add RAM |
| `npm run build` fails on old Node | need Node >= 18; install Node 20 |
| Port 8000 in use | `na serve --port 8080` (adjust firewall) |

---

## What's in the repo

`README.md` · `DASHBOARD_GUIDE.md` (how to read every screen) · `METHODS.md` (the
statistical/ML techniques) · `DATA_GENERATION.md` (generation pipeline + full column
schema). CLI: `na generate` · `na analytics` · `na report` · `na serve` · `na verify` ·
`na counts` · `na presets`.
