# 🚀 QUICK START GUIDE - Autonomous Ghost Agent

## 30-Second Launch

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Ensure Ollama is running (separate terminal)
ollama serve

# 3. In another terminal, launch the agent
python manager.py

# 4. At the prompt, type either:
#    - A specific goal: "Create a web scraper for weather data"
#    - Autonomous mode: "auto"
```

## What Happens Next

✅ **Iteration 1**: AI generates code for your goal
🚀 **Execution**: Code runs with 30-second timeout
❌ **Error?**: Auto-debugger analyzes and fixes automatically
🔄 **Retry**: Improved code runs again
✨ **Success**: Logs output and waits for next goal

---

## Key Features

### 🛡️ Failover System (3-Path Execution)
If Ollama fails → Use template fallback → Use emergency code

### 🔧 Auto-Debugger
Detects and fixes:
- Missing imports
- Indentation errors  
- Variable undefined
- Connection timeouts
- And more...

### 💾 Crash Recovery
Agent persists state. If it crashes:
1. Restart with `python manager.py`
2. It automatically resumes from last saved point
3. Continues where it left off

### 📊 Full Logging
All operations logged to `agent_logs/`:
- Real-time execution trace
- Auto-debug fix attempts
- Recovery history
- Full error tracebacks

---

## Example Usage

```
🎯 Enter goal (or 'exit'/'auto' for autonomous mode): Create a file that lists all Python files in the current directory

⏳ [Iteration 1] Generating code...
[Path 1] Calling Ollama API (Attempt 1)
✅ Ollama response successful

💡 Generated Code (v1):
==================================================
import os
import json

def list_python_files():
    py_files = [f for f in os.listdir('.') if f.endswith('.py')]
    result = {"python_files": py_files, "count": len(py_files)}
    print(json.dumps(result, indent=2))
    
if __name__ == "__main__":
    list_python_files()
==================================================

🚀 Executing code...

📊 Output:
{
  "python_files": [
    "autonomous_agent.py",
    "manager.py",
    "evolved_task.py"
  ],
  "count": 3
}

✨ Task completed successfully!
```

---

## Commands Cheat Sheet

| Command | Effect |
|---------|--------|
| `python manager.py` | Start agent in interactive mode |
| `python manager.py auto` | (after modifying main()) - Start autonomous self-maintenance |
| `exit` | Gracefully shutdown agent |
| Type any goal | Agent generates and executes code for that goal |
| Check `agent_logs/` | View all execution history and logs |

---

## Troubleshooting Quick Fixes

### Agent won't start
```bash
# Check Python version (need 3.7+)
python --version

# Verify Ollama is running
curl http://localhost:11434/api/tags

# Clear corrupted state file
rm agent_logs/agent_state.json
```

### Timeout errors
```bash
# Increase timeout from 30 to 60 seconds
set API_TIMEOUT=60
python manager.py
```

### Connection refused
```bash
# Start Ollama server (new terminal)
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

---

## Next Steps

1. **Read Full Protocol**: See `EXECUTION_PROTOCOL.md` for detailed docs
2. **Enable Autonomous Mode**: Modify `manager.py` main() to accept `auto` argument
3. **Set Environment Variables**: Copy `.env.example` to `.env` and customize
4. **Monitor Logs**: `tail -f agent_logs/agent_*.log`
5. **Daemonize**: Use `run_ghost.bat` (Windows) or `run_ghost.sh` (Linux/Mac) for true background operation

---

## Architecture Overview

```
manager.py (Main Loop)
├── ExecutionEngine (3-Path Failover)
│   ├── Path 1: Ollama API (Primary)
│   ├── Path 2: Fallback Template
│   └── Path 3: Emergency Mode
├── AutoDebugger (Self-Repair)
│   ├── Error Analysis
│   ├── Auto-Fix Application
│   └── Fix Logging
└── State Recovery (Crash Resilience)
    ├── Save state on each iteration
    ├── Persist to JSON
    └── Resume on restart
```

---

You're ready to launch! Type `python manager.py` now. 🚀
