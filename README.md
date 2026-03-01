# Multi-Company BTC Treasury Implied Value Dashboard

A Dockerized web dashboard that tracks the Bitcoin holdings of public companies and compares their current stock price against their **BTC-implied fair share price**.

**Supported Companies (v2.x):**
- **Strategy (MicroStrategy / MSTR)**
- **Strive Asset Management (ASST)**

## Formula
```
Implied Price = (BTC Price × BTC Holdings − Debt − Preferred + Cash) ÷ Fully Diluted Shares
```
If **Current Price ≤ Implied Price** → stock is trading at or below BTC-backed fair value ✅

---

## Features
- **Multi-Company Dashboard:** Seamlessly switch between MSTR and ASST using a sticky tab bar. Dynamic UI theming based on the selected company.
- **Automated Data Fetching:** Direct JSON API integration with `strategytracker.com` and `strategy.com` for robust, real-time metrics.
- **Daily Telegram Reports:** Receive a consolidated daily summary message on Telegram for all tracked companies, including market price, implied value, and premium/discount percentages.
- **Historical Tracking:** Saves daily snapshots to SQLite to plot discount/premium trends over time.

---

## Quick Start (Local)

### 1. Configure Environment
Create a `.env` file in the root directory for Telegram notifications (optional):
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 2. Build & Run
```bash
# Build & run
docker-compose up --build -d

# Open dashboard
# Windows/Linux: http://localhost:8000
# macOS: open http://localhost:8000

# View logs
docker-compose logs -f
```

### 3. Manual Refresh
Skip waiting for the scheduled 4 PM ET refresh:
```bash
# Refresh a specific company
curl -X POST "http://localhost:8000/api/refresh?company=ASST"

# Refresh all companies
curl -X POST "http://localhost:8000/api/refresh?company=all"
```

---

## Deploy on Google Cloud Free Tier (e2-micro)

### Prerequisites
- Google Cloud account with billing enabled  
- GCP Free Tier: **e2-micro VM** in `us-central1`, `us-west1`, or `us-east1`  
- 30 GB standard persistent disk (free)

### Step 1 — Create the VM

Via `gcloud` CLI:
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

### Step 4 — Access the dashboard

```
http://<YOUR-VM-EXTERNAL-IP>:8000
```

---

## Data Sources

| Company | Data | Source |
|---|---|---|
| **MSTR** | Price, Debt, Preferred, Shares | `https://api.strategy.com/btc/mstrKpiData` (with HTML scraping fallback) |
| **ASST** | Price, Debt, Preferred, Shares | `https://data.strategytracker.com` (Versioned JSON API) |
| **Global** | Live BTC Price | CoinGecko API → Binance API (fallback) |

## Refresh Schedule

Data is refreshed **once daily at 21:05 UTC** (4:05 PM US Eastern) on weekdays, shortly after the US stock market closes. 

At this time, a **Telegram Daily Report** is automatically dispatched to the configured `TELEGRAM_CHAT_ID`.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/companies` | List of supported companies and metadata (color themes, tickers) |
| `GET /api/data?company=MSTR` | Latest snapshot with all values for the specified company |
| `GET /api/history?company=MSTR&limit=90` | Historical snapshots for charting |
| `POST /api/refresh?company=all` | Trigger immediate data refresh (accepts `all` or ticker) |
| `GET /api/health` | Health check |

## Project Structure

```
.
├── backend/
│   ├── main.py         # FastAPI application & server
│   ├── fetcher.py      # Multi-company data fetching (APIs + Scraping)
│   ├── calculator.py   # Fair value formula logic
│   ├── refresh.py      # Orchestrator for data retrieval
│   ├── scheduler.py    # Daily APScheduler job
│   ├── database.py     # SQLite schema & queries
│   ├── notifier.py     # Telegram alerts & daily reports
│   └── requirements.txt
├── frontend/
│   └── index.html      # Responsive Dashboard (Chart.js, vanilla JS, CSS variables)
├── data/               # SQLite DB (Docker volume map)
├── Dockerfile
├── docker-compose.yml
└── deploy-gcp.sh       # GCP setup script
```
