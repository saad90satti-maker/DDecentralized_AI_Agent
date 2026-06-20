# 🤖 AUTONOMOUS GHOST AGENT - EXECUTION PROTOCOL

## Phase 1: Pre-Launch Setup (5 mins)

### 1.1 Environment Configuration
```bash
# Set environment variables (Create .env file or export these):
set OLLAMA_URL=http://localhost:11434/api/generate
set OLLAMA_MODEL=llama3.2:1b
set API_TIMEOUT=30
```

### 1.2 Verify Dependencies
```bash
# Install required packages
pip install --upgrade pip
pip install google-generativeai
# Note: urllib and json are built-in

# Verify Ollama is running
curl http://localhost:11434/api/tags
# Should return: {"models": [...]}
```

### 1.3 Initialize Agent Directories
```bash
# The agent auto-creates:
# - agent_logs/          (all execution logs)
# - agent_logs/agent_state.json (crash recovery state)
# - agent_logs/auto_debug.json (auto-fix history)
# - evolved_task.py (current execution code)
```

---

## Phase 2: Full Execution (Autonomous Mode)

### 2.1 Launch the Ghost Agent
```bash
# Standard mode (interactive goals):
python manager.py

# Then input goals as needed:
# Example: "Create a file backup system"
# Example: "Monitor CPU usage and alert if >80%"
```

### 2.2 Autonomous Self-Sustaining Loop
```bash
python manager.py

# At the prompt, type: auto
# This triggers autonomous maintenance mode:
# ✓ Checks system health
# ✓ Self-monitors for crashes
# ✓ Logs all operations
# ✓ Runs indefinitely until 'exit' is pressed
```

### 2.3 Execution Flow (What Happens Automatically)

```
┌─────────────────────────────────────────────────────────────┐
│                  AUTONOMOUS LOOP START                       │
└─────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │  1. GOAL INPUT                          │
        │  (User provides task or 'auto' mode)   │
        └─────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │  2. SAVE STATE                          │
        │  (Persist goal + iteration for recovery)│
        └─────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │  3. GENERATE CODE (With Failover)      │
        │  ├─ Path 1: Ollama API (Primary)       │
        │  ├─ Path 2: Fallback Template          │
        │  └─ Path 3: Emergency Minimal Code     │
        └─────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │  4. EXECUTE CODE                        │
        │  ├─ With 30s timeout                   │
        │  ├─ Capture output & errors            │
        │  └─ Check return code                  │
        └─────────────────────────────────────────┘
                              ↓
                   ┌──────────┴──────────┐
                   ↓                     ↓
              SUCCESS?              FAILED?
                   ↓                     ↓
           ✨ Complete          🔧 Auto-Debug Engine
              Break Loop              ├─ Analyze Error
              Next Goal               ├─ Auto-Fix Code
                                      ├─ Log Fix Attempt
                                      └─ Retry (Next Iter)
                                      
                   (Repeat up to 5 iterations per goal)
                              ↓
        ┌─────────────────────────────────────────┐
        │  5. CRASH RECOVERY (If Timeout/Exception)
        │  ├─ Save state to JSON                  │
        │  ├─ Log full traceback                  │
        │  └─ Ready for Resume on Restart         │
        └─────────────────────────────────────────┘
                              ↓
                    ┌──────────────────┐
                    │ Loop Back to      │
                    │ Goal Input        │
                    └──────────────────┘
```

---

## Phase 3: Auto-Debug Features (How Self-Correction Works)

### 3.1 Error Detection System
The agent automatically detects these error patterns:

| Error Type | Detection | Auto-Fix |
|-----------|-----------|----------|
| `IndentationError` | Regex scan for indent | Normalize spacing |
| `ModuleNotFoundError` | Exception text match | Add import statements |
| `NameError` | Variable undefined | Wrap with try-catch |
| `TimeoutError` | Subprocess timeout | Add retry logic |
| `ConnectionError` | Network failure | Add connectivity checks |

### 3.2 Triggering Auto-Debug
```python
# When execution fails with return code != 0:
debugger.analyze_error(error_output, current_code)

# This function:
# 1. Parses error message
# 2. Identifies error type
# 3. Applies targeted fix
# 4. Logs fix in auto_debug.json
# 5. Retries execution (next iteration)
```

### 3.3 View Auto-Debug History
```bash
# Check what fixes were applied:
cat agent_logs/auto_debug.json

# Example output:
# [
#   {
#     "timestamp": "2026-06-16T14:30:45",
#     "error_type": "IndentationError",
#     "original_lines": 45,
#     "fixed_lines": 45
#   },
#   ...
# ]
```

---

## Phase 4: Crash Recovery (Self-Healing)

### 4.1 Automatic Recovery on Restart
```bash
# If agent crashes mid-execution:
python manager.py

# On startup, it checks for previous crash:
# 🔄 RECOVERING FROM PREVIOUS CRASH
# Last goal: "Create file backup"
# Last iteration: 3
# Last error: [full traceback]

# The agent will:
# ✓ Resume from saved state
# ✓ Skip completed iterations
# ✓ Retry failed code
# ✓ Continue autonomously
```

### 4.2 State File Structure
```json
{
  "timestamp": "2026-06-16T14:30:45.123456",
  "goal": "Monitor system and create alerts",
  "current_code": "import sys\nprint('test')",
  "iteration": 3,
  "last_error": "ConnectionError: [Errno 10061]",
  "status": "active"
}
```

### 4.3 Recovery Modes

**Mode A: Graceful Resume**
- Previous code was valid but failed execution
- Auto-fixes error and retries

**Mode B: Regenerate & Retry**
- Previous code had logic error
- Agent generates improved version
- Applies auto-fixes if needed

**Mode C: Fallback Execution**
- Ollama unavailable during recovery
- Switch to fallback template or emergency code
- Ensures continuity

---

## Phase 5: Monitoring & Logging

### 5.1 Live Log Output
```
🧠 AUTONOMOUS GHOST AGENT INITIATED
============================================================
🎯 Enter goal (or 'exit'/'auto' for autonomous mode): auto
🤖 AUTONOMOUS MODE: Running self-maintenance routine
[2026-06-16 14:30:45] INFO - State saved: Iteration 0
[2026-06-16 14:30:46] INFO - 🔄 Attempting execution path: Ollama
[2026-06-16 14:30:47] INFO - ✅ Ollama response successful
[2026-06-16 14:30:48] INFO - 🚀 Executing code...
```

### 5.2 View Detailed Logs
```bash
# All logs stored in timestamped files:
ls agent_logs/

# View current session:
tail -f agent_logs/agent_YYYYMMDD_HHMMSS.log

# View auto-debug attempts:
cat agent_logs/auto_debug.json | python -m json.tool

# View recovery state:
cat agent_logs/agent_state.json | python -m json.tool
```

### 5.3 Customizing Log Levels
In `manager.py`, modify:
```python
logging.basicConfig(
    level=logging.DEBUG,  # Change to DEBUG, INFO, WARNING, ERROR
    format='%(asctime)s - %(levelname)s - %(message)s'
)
```

---

## Phase 6: Advanced Configurations

### 6.1 Custom Timeout Settings
```bash
# Increase timeout for long-running tasks:
set API_TIMEOUT=120

# Then run:
python manager.py
```

### 6.2 Use Different LLM Models
```bash
# Change Ollama model:
set OLLAMA_MODEL=mistral:latest

# Or use different URL for remote Ollama:
set OLLAMA_URL=http://192.168.1.100:11434/api/generate
```

### 6.3 Secure API Key Handling
Instead of hardcoding keys, use environment files:

Create `.env.local`:
```
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=llama3.2:1b
API_TIMEOUT=30
```

Then load before running:
```bash
# PowerShell:
Get-Content .env.local | ForEach-Object {
    if (-not $_.StartsWith("#")) {
        $name, $value = $_.Split("=")
        [Environment]::SetEnvironmentVariable($name, $value)
    }
}
python manager.py
```

---

## Phase 7: Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| `ConnectionError: refused` | Ollama not running | Start Ollama: `ollama serve` |
| `Timeout after 30s` | Model too slow | Increase `API_TIMEOUT` to 60+ |
| `ModuleNotFoundError` | Missing dependency | `pip install google-generativeai` |
| Agent exits after 1 iteration | Task completed | Normal behavior, start new goal |
| No logs in `agent_logs/` | Permission issue | Ensure write access to directory |
| State not recovering | Corrupted state.json | Delete `agent_logs/agent_state.json` and restart |

---

## Phase 8: True Autonomous Mode (Ghost Operation)

### 8.1 Daemonize Agent (Windows)
Create `run_ghost.bat`:
```batch
@echo off
python manager.py
if %errorlevel% neq 0 (
    echo Agent failed, restarting in 5 seconds...
    timeout /t 5
    goto :loop
)
```

Then run in background:
```bash
pythonw run_ghost.bat
```

### 8.2 Daemonize Agent (Linux/Mac)
Create `run_ghost.sh`:
```bash
#!/bin/bash
while true; do
    python manager.py auto
    sleep 5
    echo "Restarting agent..."
done
```

Run in background:
```bash
nohup bash run_ghost.sh > ghost_agent.log 2>&1 &
```

### 8.3 Monitor Running Agent
```bash
# Check if process is running
ps aux | grep manager.py

# Kill gracefully
pkill -f manager.py

# View real-time logs
tail -f agent_logs/*.log
```

---

## Summary: Complete Execution Checklist

- [ ] Set environment variables (Phase 1.1)
- [ ] Verify Ollama running (Phase 1.2)
- [ ] Run `python manager.py` (Phase 2.1)
- [ ] Input goal or type `auto` (Phase 2.2)
- [ ] Monitor logs in `agent_logs/` (Phase 5.2)
- [ ] If crash, restart to trigger recovery (Phase 4.1)
- [ ] Check `auto_debug.json` for fixes applied (Phase 3.3)
- [ ] For true ghost mode, use daemonization (Phase 8)

The agent is now fully autonomous and self-healing! 🚀
