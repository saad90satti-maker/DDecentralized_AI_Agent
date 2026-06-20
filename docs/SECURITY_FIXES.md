# 🔐 Security Fixes - Implementation Guide

## Step-by-Step Fixes for Critical Issues

### FIX 1: Remove Hard-Coded Credentials (CRITICAL)

**File**: `manager.py` (lines 54-62)

**Replace this**:
```python
class ServiceConfig:
    Gmail = {
        "user": os.getenv("GMAIL_USER", "saad90satti@gmail.com"),  # ❌ REMOVE DEFAULT
        "pass": os.getenv("GMAIL_PASS", "saad2027@saadface")       # ❌ REMOVE DEFAULT
    }
    HuggingFace = os.getenv("HUGGINGFACE_TOKEN", "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")  # ❌ REMOVE
    Groq = os.getenv("GROQ_API_KEY", "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")  # ❌ REMOVE
    GitHub = os.getenv("GITHUB_TOKEN", "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")  # ❌ REMOVE
    Cloudflare = os.getenv("CLOUDFLARE_TOKEN", "cfut_0Gq3f7IvtFuRdhQO12g3YKk7tn1znirppJxJTvfs940aaca5")  # ❌ REMOVE
    Discord = os.getenv("DISCORD_TOKEN", "MTUxNjM0MjAxMTMyNDc5Njk5OA.GB-70v.RZNBky74axckcxFlzPXwePOmbr-BUxvalqUwig")  # ❌ REMOVE
```

**With this**:
```python
from security_utils import CredentialManager

class ServiceConfig:
    @classmethod
    def get_credentials(cls):
        """Load credentials from environment only (no defaults)."""
        return CredentialManager.get_tokens()
    
    @classmethod
    def auth_status(cls):
        """Check which services are configured."""
        return CredentialManager.validate_configured()
```

---

### FIX 2: Add API Key Authentication (CRITICAL)

**File**: `manager.py` (add near top after imports)

**Add this**:
```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from security_utils import validate_api_key

security = HTTPBearer()

async def verify_auth(credentials = Depends(security)):
    """Verify API key from Authorization header."""
    if not validate_api_key(credentials.credentials):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return credentials.credentials
```

**Apply to all endpoints** (example):
```python
@app.get("/api/status")
def api_status(auth: str = Depends(verify_auth)):  # ✅ ADD AUTH
    services = connector.check_services()
    return JSONResponse({
        "services": services,
        "pending_tasks": manager.pending_tasks(),
        "recent_outputs": manager.recent_outputs(),
    })
```

---

### FIX 3: Remove shell=True and Use Safe Command Parsing (CRITICAL)

**File**: `manager.py` (ExecutionEngine.execute_command method, around line 215)

**Replace this**:
```python
completed = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
```

**With this**:
```python
from security_utils import parse_command_safely, validate_command

# First validate
valid, msg = validate_command(command)
if not valid:
    result["status"] = "error"
    result["stderr"] = msg
    return result

# Parse safely
args = parse_command_safely(command)
if not args:
    result["status"] = "error"
    result["stderr"] = "Invalid command syntax"
    return result

try:
    completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout)  # ✅ NO shell=True
except subprocess.TimeoutExpired as exc:
    result["status"] = "timeout"
    result["stderr"] = str(exc)
    recovery.log_failure(str(exc), "execute_command_timeout")
    return result
```

---

### FIX 4: Sanitize Logs (HIGH)

**File**: `manager.py` (in recovery logging)

**Replace this**:
```python
logger.error(f"Recovery: {message} | {context}")
```

**With this**:
```python
from security_utils import sanitize_for_logging

safe_message = sanitize_for_logging(message)
safe_context = sanitize_for_logging(context)
logger.error(f"Recovery: {safe_message} | {safe_context}")
```

---

### FIX 5: Add Input Validation (HIGH)

**File**: `manager.py` (in api_cli function)

**Replace this**:
```python
@app.post("/api/cli")
def api_cli(cmd_input: Dict[str, Any]):
    action = cmd_input.get("action", "").lower()
```

**With this**:
```python
from security_utils import validate_action, CLIAction

@app.post("/api/cli")
def api_cli(cmd_input: Dict[str, Any], auth: str = Depends(verify_auth)):
    valid, action = validate_action(cmd_input.get("action", ""))
    if not valid:
        return JSONResponse({"status": "error", "message": "Invalid action"}, status_code=400)
    # Now action is a validated CLIAction enum
```

---

### FIX 6: Add Rate Limiting (HIGH)

**File**: `manager.py` (add to imports)

**Add this**:
```bash
# First install: pip install slowapi
```

**Then add to manager.py**:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse(
    {"error": "Too many requests"}, status_code=429
))
```

**Apply to endpoints**:
```python
@app.get("/api/status")
@limiter.limit("10/minute")  # ✅ ADD RATE LIMIT
def api_status(request: Request, auth: str = Depends(verify_auth)):
    ...
```

---

### FIX 7: Add Security Headers (MEDIUM)

**File**: `manager.py` (in main or right after app creation)

**Add this**:
```python
from security_utils import add_security_headers, add_request_size_limit

# After app = FastAPI(...)
add_security_headers(app)
add_request_size_limit(app)
```

---

### FIX 8: Secure File Permissions (HIGH)

**File**: `manager.py` (initialization section)

**Replace this**:
```python
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
```

**With this**:
```python
from security_utils import secure_file

LOG_DIR.mkdir(mode=0o700, exist_ok=True)  # Owner only
DATA_DIR.mkdir(mode=0o700, exist_ok=True)

# Secure all sensitive files
secure_file(LOG_FILE)
secure_file(TASK_QUEUE)
secure_file(STATE_FILE)
secure_file(RECOVERY_FILE)
```

---

### FIX 9: Remove shell=True from hermes_bridge.py (HIGH)

**File**: `hermes_bridge.py` (in send_prompt_cli method)

**Replace this**:
```python
cmd = f"ollama run {shlex.quote(self.model)} --prompt {shlex.quote(prompt)}"
completed = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
```

**With this**:
```python
# Use list format without shell=True
proc = subprocess.run(
    ["ollama", "run", self.model],
    input=prompt.encode("utf-8"),
    capture_output=True,
    text=False,  # Get bytes to handle encoding
    timeout=60
)
# Decode safely with error handling
out = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
err = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
return {
    "status": "success" if proc.returncode == 0 else "error",
    "stdout": out.strip(),
    "stderr": err.strip(),
    "returncode": proc.returncode,
}
```

---

### FIX 10: Configure CORS for Production (MEDIUM)

**File**: `manager.py` (after app creation)

**Add this**:
```python
from fastapi.middleware.cors import CORSMiddleware

# Restrict to trusted origins
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    os.getenv("ALLOWED_ORIGINS", "").split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins if o],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

## Updated requirements.txt

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
requests==2.31.0
aiohttp==3.9.1
python-dotenv==1.0.0
discord.py==2.3.2
playwright==1.40.0
google-generativeai>=0.3.0
slowapi==0.1.9
cryptography==41.0.7
```

---

## Updated .env Variables

```env
# API Authentication
GHOST_API_KEY=generate_a_strong_random_key_here_min_32_chars

# Gmail (NO DEFAULTS)
GMAIL_USER=your_email@gmail.com
GMAIL_PASS=your_app_password

# API Keys (NO DEFAULTS)
HUGGINGFACE_TOKEN=hf_your_token
GROQ_API_KEY=gsk_your_key
GITHUB_TOKEN=ghp_your_token
CLOUDFLARE_TOKEN=cfut_your_token
DISCORD_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=channel_id

# Settings
HERMES_URL=http://localhost:11434
HERMES_MODEL=llama3.2:1b
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
LOG_LEVEL=INFO
```

---

## Testing Security Fixes

```bash
# 1. Test API key requirement
curl http://localhost:8000/api/status
# Should get 403 Forbidden

curl -H "Authorization: Bearer YOUR_API_KEY" http://localhost:8000/api/status
# Should work

# 2. Test command injection protection
python cli.py execute "echo test; rm -rf /"
# Should reject with "Command contains dangerous patterns"

# 3. Test rate limiting
for i in {1..15}; do curl -H "Authorization: Bearer KEY" http://localhost:8000/api/status; done
# Should rate limit after 10 requests/minute

# 4. Test input validation
curl -H "Authorization: Bearer KEY" -X POST http://localhost:8000/api/cli \
  -H "Content-Type: application/json" \
  -d '{"action": "invalid_action"}'
# Should return error

# 5. Check file permissions
ls -la agent_logs/
ls -la agent_data/
# Should show 700 (rwx------)
```

---

## Deployment Security Checklist

Before deploying to production:

- [ ] Remove all hard-coded credentials
- [ ] Set `GHOST_API_KEY` environment variable
- [ ] Generate new API tokens
- [ ] Revoke old tokens from GitHub
- [ ] Enable HTTPS/TLS
- [ ] Set up WAF (Web Application Firewall)
- [ ] Enable audit logging
- [ ] Configure backup strategy for logs
- [ ] Set up monitoring/alerting
- [ ] Perform security scan with OWASP ZAP
- [ ] Get security review by third party
- [ ] Set up incident response plan

---

**Status**: Implementation Guide Complete

**Next Steps**:
1. Apply fixes in order of severity (Critical first)
2. Test each fix
3. Run security tests
4. Revoke all exposed credentials
5. Deploy to production with confidence
