# 📖 Ghost Engine - Command Reference

## Dashboard (Web UI)

**URL**: http://localhost:8000

### Panels
- **Active Services**: Shows status of all integrations (Gmail, GitHub, Discord, etc.)
- **Pending Tasks**: Lists queued tasks awaiting execution
- **Recent Output**: Displays execution results
- **Command Terminal**: Execute shell commands directly
- **Deployment Options**: Prepare and deploy to cloud
- **Task Queue**: Add new tasks to the execution queue

---

## CLI Commands

**Launch**: `python cli.py [command] [args]`

### Status & Monitoring
```bash
python cli.py status                # Show active services and pending tasks
python cli.py logs                  # Show recent execution logs
```

### Task Execution
```bash
python cli.py execute "CMD"         # Execute immediately: python cli.py execute "ls -la"
python cli.py task "CMD"            # Queue for background execution: python cli.py task "python worker.py"
```

### Intelligence
```bash
python cli.py think "TEXT"          # Send to Hermes for analysis: python cli.py think "Explain quantum computing"
python cli.py hermes "TEXT"         # Same as think (alias): python cli.py hermes "What is deep learning?"
```

### System Management
```bash
python cli.py deploy                # Prepare GitHub Actions deployment
python cli.py scale N               # Set max parallel workers: python cli.py scale 16
```

### Notifications
```bash
python cli.py discord "MESSAGE"     # Send Discord notification: python cli.py discord "Deployment started"
```

### Help
```bash
python cli.py help                  # Show this help message
```

---

## Discord Bot Commands

**Prefix**: `!`  
**Launch**: `python discord_bot.py`

```bash
!status                    # Show service status
!execute CMD               # Execute command: !execute python script.py
!task CMD                  # Queue task: !task python worker.py arg1
!think TEXT                # Send to Hermes: !think What is machine learning?
!deploy                    # Prepare deployment
!scale N                   # Set workers: !scale 8
!help                      # Show help
```

### Example Discord Usage
```
User: !status
Bot: {JSON response with all services}

User: !execute echo "Hello"
Bot: {JSON response with "Hello" output}

User: !think summarize the benefits of machine learning
Bot: {Hermes analysis response}
```

---

## REST API Endpoints

**Base URL**: http://localhost:8000

### Status & Info
```bash
GET /api/status
# Response: {services: {...}, pending_tasks: [...], recent_outputs: [...]}

GET /api/logs
# Response: {outputs: [...]}
```

### Task Management
```bash
POST /api/execute
# Payload: {"command": "echo test", "parallel": false}
# Response: {status: "success", stdout: "test", ...}

POST /api/task
# Payload: {"command": "python script.py"}
# Response: {status: "queued", task: {...}}

POST /api/retry
# Payload: {"command": "echo retry"}
# Response: {status: "retry_queued", task: {...}}
```

### Intelligence
```bash
POST /api/hermes
# Payload: {"text": "Explain AI"}
# Response: {status: "success", hermes_response: {...}}

POST /api/cli
# Payload: {"action": "status|execute|think|deploy|scale", "args": [...]}
# Response: {status: "success", ...}
```

### Notifications
```bash
POST /api/discord
# Payload: {"content": "Hello Discord"}
# Response: {status: "success", sent: true}
```

### Deployment
```bash
POST /api/deploy
# Response: {status: "ready", workflow_path: "..."}
```

---

## Browser Automation

**Module**: `browser_agent.py`

### Python Usage
```python
from browser_agent import BrowserAgent
import asyncio

async def automate():
    async with BrowserAgent(headless=True) as agent:
        await agent.goto("https://example.com")
        await agent.fill_form({"email": "user@example.com", "password": "secret"})
        await agent.click("button[type='submit']")
        await agent.screenshot("result.png")

asyncio.run(automate())
```

### Available Methods
- `goto(url)` - Navigate to URL
- `fill_form(fields)` - Fill form fields
- `click(selector)` - Click element
- `get_text(selector)` - Get element text
- `screenshot(path)` - Take screenshot
- `wait_for_selector(selector, timeout)` - Wait for element
- `execute_script(script, arg)` - Run JavaScript
- `get_cookies()` - Get all cookies
- `airdrop_claim_workflow(url, form_data)` - Airdrop claiming template

---

## Configuration Commands

### Start Dashboard
```bash
python manager.py
```

### Start Discord Bot
```bash
python discord_bot.py
```

### Test Hermes Integration
```bash
python hermes_bridge.py
```

### View Logs
```bash
# View dashboard logs
tail -f agent_logs/manager_*.log

# View recovery log
cat agent_logs/recovery.log

# View task queue
cat agent_data/task_queue.json

# View execution state
cat agent_data/agent_state.json
```

---

## Common Workflows

### Deploy to Cloud
```bash
# 1. Prepare deployment
python cli.py deploy

# 2. Push to GitHub
git add .github/workflows/python-app.yml
git commit -m "Add deployment workflow"
git push

# 3. Deploy on Render.com or Railway.app
# (Connect your GitHub repo in their dashboard)
```

### Run Parallel Tasks
```bash
# Set workers to 16
python cli.py scale 16

# Execute with parallel flag
curl -X POST http://localhost:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "python task.py", "parallel": true}'
```

### Monitor Execution
```bash
# Check status in real-time
watch -n 1 "python cli.py status"

# View logs
python cli.py logs | python -m json.tool

# Check for failures
grep "ERROR\|FAIL" agent_logs/recovery.log
```

### Setup Local Hermes
```bash
# 1. Install Ollama
# Download from https://ollama.ai

# 2. Run Ollama service
ollama serve

# 3. Pull model (in another terminal)
ollama pull llama3.2:1b

# 4. Test
python cli.py think "Hello, this is a test"
```

---

## Troubleshooting Commands

### Port Already In Use
```bash
netstat -ano | findstr :8000
taskkill /PID <PID> /F
python manager.py
```

### Check Service Connectivity
```bash
python cli.py status
```

### View Recovery Log
```bash
cat agent_logs/recovery.log
```

### Clear Task Queue
```bash
rm agent_data/task_queue.json
# (Will be recreated automatically)
```

### Test API Directly
```bash
# Test status endpoint
curl http://localhost:8000/api/status

# Test execute endpoint
curl -X POST http://localhost:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{"command": "echo test"}'
```

---

## Environment Variables

```bash
# API & Services
MANAGER_URL=http://localhost:8000
HERMES_URL=http://localhost:11434
HERMES_MODEL=llama3.2:1b

# Auth
GMAIL_USER=your@email.com
GMAIL_PASS=app_password
GROQ_API_KEY=gsk_...
GITHUB_TOKEN=ghp_...
DISCORD_TOKEN=MTxxxxxx
DISCORD_CHANNEL_ID=channel_id

# Deployment
RENDER_SERVICE_ID=...
RAILWAY_API_TOKEN=...
```

---

## Performance Tuning

```bash
# Increase parallel workers
python cli.py scale 32

# Check current status
python cli.py status

# Monitor logs in real-time
tail -f agent_logs/manager_*.log

# Profile execution
python -m cProfile -s cumulative manager.py
```

---

## Advanced Usage

### Custom Execution with Parallel
```python
import requests

result = requests.post(
    "http://localhost:8000/api/execute",
    json={"command": "python cpu_intensive_task.py", "parallel": True}
)
print(result.json())
```

### Schedule Tasks via Cron
```bash
# Add to crontab
0 2 * * * /usr/bin/python3 /path/to/cli.py task "python maintenance_job.py"
```

### Webhook Integration
```bash
# Send task from external service
curl -X POST http://localhost:8000/api/task \
  -H "Content-Type: application/json" \
  -d '{"command": "python external_trigger.py"}'
```

---

**For more info, see**: README.md, QUICK_START.md, SYSTEM_STATUS.md
