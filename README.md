# 🤖 Ghost Engine - Decentralized AI Agent Suite

A production-ready, cloud-deployable autonomous AI system with multi-layer control: FastAPI dashboard, CLI, Discord bot, browser automation, and local Hermes/Ollama integration.

## Features

### Core Components
- **FastAPI Dashboard** (`manager.py`) - Live web interface at `localhost:8000`
- **CLI Tool** (`cli.py`) - Command-line interface with full control
- **Discord Bot** (`discord_bot.py`) - Remote command execution via Discord
- **Browser Agent** (`browser_agent.py`) - Playwright-based web automation
- **Hermes Bridge** (`hermes_bridge.py`) - Local LLM integration (llama3.2:1b or fallback to Groq)
- **Task Queue** - Persistent async task execution with auto-recovery
- **Service Connectors** - Gmail, GitHub, Discord, Cloudflare, HuggingFace, Groq, Ollama

### 7-Step Architecture
1. **System Core** - Python execution engine with parallel processing
2. **API Gateway** - FastAPI REST endpoints
3. **Browser Automation** - Playwright for web interaction
4. **Execution Engine** - Subprocess management with auto-repair
5. **Autonomous Loop** - Task queue with self-healing
6. **Cloud Bridge** - GitHub Actions and cloud platform support
7. **Ecosystem** - Multi-service orchestration

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file:
```env
GMAIL_USER=your_email@gmail.com
GMAIL_PASS=your_app_password
HUGGINGFACE_TOKEN=hf_xxxxx
GROQ_API_KEY=gsk_xxxxx
GITHUB_TOKEN=ghp_xxxxx
CLOUDFLARE_TOKEN=cfut_xxxxx
DISCORD_TOKEN=MTxxxxxx
DISCORD_CHANNEL_ID=channel_id
HERMES_URL=http://localhost:11434
HERMES_MODEL=llama3.2:1b
```

### 3. Start the Dashboard
```bash
python manager.py
# Access at http://localhost:8000
```

### 4. Use the CLI
```bash
python cli.py status
python cli.py execute "ls -la"
python cli.py think "What are the key features?"
python cli.py deploy
python cli.py scale 8
```

### 5. Start Discord Bot (Optional)
```bash
python discord_bot.py
# Commands: !status, !execute CMD, !task CMD, !think TEXT, !deploy, !scale N
```

## API Endpoints

### Status & Monitoring
- `GET /api/status` - Service status and pending tasks
- `GET /api/logs` - Recent execution logs

### Task Management
- `POST /api/task` - Queue a task: `{"command": "..."}`
- `POST /api/execute` - Execute immediately: `{"command": "...", "parallel": false}`
- `POST /api/retry` - Retry a task: `{"command": "..."}`

### Intelligence
- `POST /api/hermes` - Analyze with Hermes: `{"text": "..."}`
- `POST /api/cli` - CLI commands: `{"action": "status|execute|think|deploy|scale", "args": [...]}`

### Notifications
- `POST /api/discord` - Send notification: `{"content": "..."}`

### Deployment
- `POST /api/deploy` - Prepare GitHub Actions deployment

## File Structure

```
d:\DDecentralized_AI_Agent\
├── manager.py              # FastAPI dashboard & task engine
├── hermes_bridge.py        # Hermes/Ollama integration
├── cli.py                  # Command-line interface
├── discord_bot.py          # Discord bot (optional)
├── browser_agent.py        # Playwright automation
├── autonomous_agent.py     # Original agent (legacy reference)
├── python_manager.py       # Legacy manager (reference)
├── requirements.txt        # Python dependencies
├── .env.example            # Environment template
├── agent_logs/             # Execution logs and recovery
├── agent_data/             # Task queue and state
└── .github/workflows/      # GitHub Actions deployment
```

## CLI Commands

```
status              Show active services and pending tasks
execute CMD         Execute a local shell command
think TEXT          Send text to Hermes for analysis
task CMD            Enqueue a task for async execution
deploy              Prepare GitHub Actions workflow
scale N             Set max parallel workers to N
hermes TEXT         Direct Hermes analysis (same as think)
discord MSG         Send Discord notification
logs                Show recent output logs
help                Show this help message
```

### Examples
```bash
python cli.py status
python cli.py execute "python script.py arg1 arg2"
python cli.py think "Summarize the benefits of async processing"
python cli.py task "python long_running_job.py"
python cli.py deploy
python cli.py scale 16
python cli.py discord "Deployment complete!"
```

## Discord Bot Commands

Prefix: `!`

```
!status               Show service status
!execute CMD          Execute a command
!task CMD             Queue a task
!think TEXT           Send to Hermes for analysis
!deploy               Prepare deployment
!scale N              Set max workers to N
!help                 Show help
```

## Browser Automation

```python
from browser_agent import BrowserAgent
import asyncio

async def main():
    async with BrowserAgent(headless=False) as agent:
        await agent.goto("https://example.com")
        await agent.fill_form({"email": "user@example.com", "password": "secret"})
        await agent.click("button:has-text('Submit')")
        await agent.screenshot("result.png")

asyncio.run(main())
```

## Local Hermes Setup

### Option 1: Ollama (Recommended)
```bash
# Install Ollama from https://ollama.ai
# Run the Ollama service
ollama serve

# In another terminal, pull the model
ollama pull llama3.2:1b

# Ghost Engine will auto-connect via hermes_bridge.py
```

### Option 2: Fallback to Groq API
If Ollama is offline, the system falls back to the Groq API using your `GROQ_API_KEY`.

## Cloud Deployment

### GitHub Actions
```bash
python cli.py deploy
# Creates .github/workflows/python-app.yml
```

### Render.com
```bash
# Deploy the GitHub repo to Render
# Set environment variables in Render dashboard
# Point to this repository and deploy
```

### Railway.app
```bash
# Similar to Render
# Connect your GitHub repo
# Set environment variables
# Deploy automatically on push
```

## Execution Rules

- **Never delete old code** - Only add upgrades as layers
- **Never stop for errors** - Auto-repair and continue
- **Always auto-install** - Missing packages are installed automatically
- **Always multithread** - Parallel execution by default
- **Persistent recovery** - Failed tasks are logged and retried

## Architecture Layers

```
┌─────────────────────────────────────────┐
│   Discord Bot / CLI / Browser UI        │  User Interfaces
├─────────────────────────────────────────┤
│   FastAPI Dashboard (localhost:8000)    │  Web Interface
├─────────────────────────────────────────┤
│   Task Queue & Service Orchestrator     │  Coordination
├─────────────────────────────────────────┤
│   Execution Engine (subprocess)         │  Execution
├─────────────────────────────────────────┤
│   Recovery Module & Auto-Repair         │  Resilience
├─────────────────────────────────────────┤
│   Service Connectors (Gmail, GitHub...) │  Integrations
├─────────────────────────────────────────┤
│   Hermes Bridge (Ollama/Groq)           │  Intelligence
└─────────────────────────────────────────┘
```

## Monitoring

- View logs: `http://localhost:8000/api/logs`
- CLI: `python cli.py logs`
- Log files: `agent_logs/manager_*.log`
- Recovery log: `agent_logs/recovery.log`

## Troubleshooting

### Port 8000 already in use
```bash
netstat -ano | findstr :8000
taskkill /PID <PID> /F
python manager.py
```

### Hermes model not found
```bash
# Install Ollama first
ollama pull llama3.2:1b
# Or configure GROQ_API_KEY as fallback
```

### Discord notifications not working
- Check `DISCORD_TOKEN` and `DISCORD_CHANNEL_ID` are set
- Verify bot has message send permissions

### Tasks not executing
- Check `agent_data/task_queue.json` for pending tasks
- Review logs in `agent_logs/`
- Ensure execution engine is running

## Development

### Adding Custom Endpoints
Edit `manager.py` and add new routes:
```python
@app.post("/api/custom")
def api_custom(payload: Dict[str, Any]):
    # Your logic here
    return JSONResponse({"status": "success", "data": ...})
```

### Adding Custom Service Connectors
Add to `ServiceConfig` class in `manager.py`:
```python
class ServiceConfig:
    MyService = os.getenv("MY_SERVICE_TOKEN", "default_value")
```

## Performance Tips

- Increase `scale` for parallel execution: `python cli.py scale 32`
- Use `parallel: true` in execute endpoint for CPU-intensive tasks
- Monitor task queue size: `python cli.py status`
- Archive old logs: `agent_logs/` directory

## License

This project is provided as-is for local automation and testing purposes.

## Support

For issues or questions, check:
1. Recent log files in `agent_logs/`
2. Recovery log: `agent_logs/recovery.log`
3. Task queue: `agent_data/task_queue.json`
4. API response in CLI: `python cli.py status`
