# MSTR BTC Treasury Implied Value Dashboard

A Dockerized web dashboard that compares MicroStrategy's (MSTR) current stock price against its **BTC-implied fair share price**.

## Formula
```
Implied Price = (BTC Price × BTC Holdings − Debt − Preferred + Cash) ÷ Fully Diluted Shares
```
If **Current Price ≤ Implied Price** → stock is trading at or below BTC-backed fair value ✅

---

## Quick Start (Local)

```bash
# Build & run
docker-compose up --build -d

# Open dashboard
open http://localhost:8000

# View logs
docker-compose logs -f

# Manual data refresh (skip waiting for 4 PM ET)
curl -X POST http://localhost:8000/api/refresh
```

---

## Deploy on Google Cloud Free Tier (e2-micro)

### Prerequisites
- Google Cloud account with billing enabled  
- GCP Free Tier: **e2-micro VM** in `us-central1`, `us-west1`, or `us-east1`  
- 30 GB standard persistent disk (free)

### Step 1 — Create the VM

In **Google Cloud Console → Compute Engine → Create Instance**:

| Setting | Value |
|---|---|
| Machine type | `e2-micro` |
| Region | `us-central1` (or `us-west1` / `us-east1`) |
| Boot disk | Debian 12 "Bookworm", **30 GB Standard** |
| Firewall | ✅ Allow HTTP (port 80) & HTTPS (port 443) |

Or via `gcloud` CLI:
```bash
gcloud compute instances create btc-treasury \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --tags=http-server
```

### Step 2 — Open port 8000 in the firewall

```bash
gcloud compute firewall-rules create allow-btc-treasury \
  --allow tcp:8000 \
  --target-tags=http-server \
  --description="BTC Treasury dashboard"
```

### Step 3 — SSH into the VM and deploy

```bash
# SSH in
gcloud compute ssh btc-treasury --zone=us-central1-a

# Clone / copy project files to VM, then:
cd /path/to/project

# Run the one-shot setup script
chmod +x deploy-gcp.sh
./deploy-gcp.sh
```

The script will:
1. Install Docker CE
2. Build the Docker image
3. Start the container with `docker-compose up -d`

### Step 4 — Access the dashboard

```
http://<YOUR-VM-EXTERNAL-IP>:8000
```

Find your external IP:
```bash
gcloud compute instances describe btc-treasury \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

---

## Data Sources

| Data | Source |
|---|---|
| MSTR Price, Debt, Preferred | `https://api.strategy.com/btc/mstrKpiData` |
| Fully Diluted Shares, BTC Holdings | `https://www.strategy.com/shares` (scraped) |
| Cash (USD Reserve) | `https://www.strategy.com/` (scraped) |
| Live BTC Price | CoinGecko → Binance (fallback) |

## Refresh Schedule

Data is refreshed **once daily at 21:05 UTC** (4:05 PM US Eastern) on weekdays, after US stock market close.

You can also trigger a manual refresh:
```bash
curl -X POST http://localhost:8000/api/refresh
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/data` | Latest snapshot with all values |
| `GET /api/history?limit=90` | Historical snapshots (up to 365) |
| `POST /api/refresh` | Trigger immediate data refresh |
| `GET /api/health` | Health check |

## Project Structure

```
.
├── backend/
│   ├── main.py         # FastAPI app
│   ├── fetcher.py      # Data fetching (API + scraping)
│   ├── calculator.py   # Formula logic
│   ├── refresh.py      # Orchestrator
│   ├── scheduler.py    # Daily APScheduler job
│   ├── database.py     # SQLite schema & queries
│   └── requirements.txt
├── frontend/
│   └── index.html      # Dashboard (Chart.js, vanilla JS)
├── data/               # SQLite DB (Docker volume)
├── Dockerfile
├── docker-compose.yml
└── deploy-gcp.sh       # GCP setup script
```
