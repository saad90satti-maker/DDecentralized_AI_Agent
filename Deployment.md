# Ghost Engine — Deployment Guide

## Prerequisites
- Python 3.10+
- Git
- A cloud account (Render, Railway, or similar)

## Local Setup
```bash
git clone <your-repo-url>
cd DDecentralized_AI_Agent
pip install -r requirements.txt
cp .env.example .env   # fill in your API keys
```

## Services & How to Run

| Service | Command | Port |
|---------|---------|------|
| FastAPI Dashboard | `python app.py` or `python manager.py` | 7860 / 8000 |
| CLI Interface | `python cli.py` | — |
| Full Daemon | `python main.py` | — |
| Discord Bot | `python discord_bot.py` | — |
| Browser Agent | `python browser_agent.py` | — |

## Cloud Deployment

### Option 1: Render
1. Connect your GitHub repo to Render
2. Select **Web Service** → set **Start Command**: `python app.py`
3. Set environment variables (see `.env.example`)
4. Deploy — Render handles HTTPS + auto-restarts

### Option 2: Railway
```bash
railway login
railway init
railway up
```
Railway auto-detects `requirements.txt` and `Procfile`.

### Option 3: Docker
```bash
docker compose up --build
```
Exposes dashboard at `localhost:8000`.

## 24/7 Operation
- Render/Railway keep your service alive with auto-restart.
- Use `python main.py` for the autonomous daemon loop.
- The self-heal module (`self_heal.py`) auto-recovers from crashes.
