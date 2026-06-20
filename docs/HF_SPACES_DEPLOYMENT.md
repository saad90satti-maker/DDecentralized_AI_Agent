# 🚀 Hugging Face Spaces Deployment Guide

## Setup Instructions

### Step 1: Create a Hugging Face Space

1. Go to [Hugging Face Spaces](https://huggingface.co/spaces)
2. Click **Create new Space**
3. Configure:
   - **Space name**: `Decentralized-AI-Agent` (or your preferred name)
   - **License**: Choose appropriate license (MIT recommended)
   - **Space SDK**: `Docker` or `Gradio`
   - **Space hardware**: Select based on needs (free tier available)
   - **Visibility**: Public or Private

4. Note the **Space repo ID**: It will be in the format `your-username/Decentralized-AI-Agent`

---

### Step 2: Set GitHub Secrets for CI/CD Deployment

In your GitHub repository settings, add these secrets:

| Secret Name | Value |
|-------------|-------|
| `HF_TOKEN` | Your Hugging Face API token (from https://huggingface.co/settings/tokens) |
| `HF_SPACE_REPO` | Your Space repo ID (e.g., `saad2howw/Decentralized-AI-Agent`) |

**To create an HF token:**
1. Go to https://huggingface.co/settings/tokens
2. Click **New token**
3. Select **Write** access
4. Copy the token

**⚠️ IMPORTANT**: Never hardcode tokens in files. Use GitHub Secrets only.

---

### Step 3: Set Space Environment Variables

In your Hugging Face Space settings, add these environment variables:

```env
GMAIL_USER=your_email@gmail.com
GMAIL_PASS=your_app_password_or_token
HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxx
CLOUDFLARE_TOKEN=cfut_xxxxxxxxxxxxxxxxxxxxxxxx
DISCORD_TOKEN=MTxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DISCORD_CHANNEL_ID=your_channel_id
PUBLIC_WEBHOOK_URL=your_webhook_url_or_leave_empty
HERMES_URL=http://localhost:11434
HERMES_MODEL=llama3.2:1b
```

---

### Step 4: Deploy via GitHub Actions

Push your code to the `main` branch:

```bash
git add .
git commit -m "Deploy to HF Spaces"
git push origin main
```

The GitHub Actions workflow will:
1. ✅ Validate Python modules
2. ✅ Install dependencies
3. ✅ Clone/update your HF Space repo
4. ✅ Copy project files
5. ✅ Create Gradio interface
6. ✅ Commit and push to Hugging Face

**Check deployment status:**
- GitHub: Actions tab → Ghost Engine Deployment workflow
- Hugging Face: Space page → Container logs

---

### Step 5: Manual Deployment (Alternative)

If you prefer to deploy manually without GitHub Actions:

1. Install dependencies:
   ```bash
   pip install -r requirements.txt huggingface-hub gradio
   ```

2. Set environment variables:
   ```bash
   export HF_TOKEN="hf_your_token_here"
   export HF_SPACE_REPO="your-username/Decentralized-AI-Agent"
   ```

3. Run deployment script:
   ```bash
   python deploy.py
   ```

---

## File Structure for HF Spaces

The deployment creates this structure in your HF Space:

```
Decentralized-AI-Agent/
├── app.py                        # Gradio + FastAPI entry point
├── manager.py                    # FastAPI dashboard
├── requirements.txt              # Python dependencies
├── hermes_bridge.py             # LLM integration
├── stealth_browser.py           # Browser automation
├── email_agent.py               # Email workflows
├── execution_core.py            # Task execution engine
├── dashboard_instrumentation.py # Metrics store
├── security_utils.py            # Security utilities
├── .env.example                 # Environment template
└── .gitignore                   # Git ignore rules
```

---

## Access Your Deployed Space

Once deployed, access at:

```
https://huggingface.co/spaces/your-username/Decentralized-AI-Agent
```

The interface will show:
- **Command Execution tab**: Run shell commands
- **Email Management tab**: Check unread emails and manage workflows
- **AI Analysis tab**: Analyze text with Hermes/LLM
- **Dashboard**: Real-time metrics and task status

---

## Troubleshooting

### Deployment fails with "git command not found"

GitHub Actions uses git internally. Ensure:
- Your repository is properly initialized
- `.gitignore` exists and excludes `.env` files

### Space won't start / shows 404

1. Check Space settings → Runtime logs
2. Verify all environment variables are set
3. Ensure `requirements.txt` has all dependencies
4. Check `app.py` is valid Python

### Email workflows not triggering

1. Verify `GMAIL_USER` and `GMAIL_PASS` are correct
2. Enable "App passwords" in Gmail security settings
3. Check Space logs for IMAP connection errors

### Hermes/LLM not responding

1. `HERMES_URL=http://localhost:11434` only works if local
2. For HF Spaces, use a remote LLM API (Groq, HuggingFace)
3. Set `GROQ_API_KEY` for fallback LLM access

---

## Security Notes

✅ **DO:**
- Use GitHub Secrets for all tokens
- Set Space environment variables securely
- Enable HF Space authentication if needed
- Use `.env.example` as template only

❌ **DON'T:**
- Commit `.env` files with real tokens
- Share your HF token publicly
- Use tokens in GitHub workflow files (use secrets instead)
- Deploy to public internet without HTTPS

---

## Monitoring & Logs

Check deployment status:

1. **GitHub Actions**:
   - Repository → Actions → Ghost Engine Deployment

2. **Hugging Face Spaces**:
   - Space page → "Logs" tab
   - Real-time container output

3. **Task Status**:
   - Access dashboard at Space URL
   - View task queue and execution history
   - Monitor metrics in real-time

---

## Automatic Redeployment

The workflow automatically redeploys on:
- Push to `main` branch
- Manual trigger via GitHub Actions > workflow_dispatch

For continuous deployment, ensure:
1. GitHub Secrets are set
2. `.github/workflows/python-app.yml` is valid
3. `deploy.py` exists and is executable

---

## Support & Next Steps

For issues:
1. Check GitHub Actions logs
2. Review HF Space container logs
3. Verify all environment variables
4. Test locally first: `python manager.py`

For enhancements:
- Add more Gradio tabs
- Integrate additional services
- Customize UI styling
- Add webhooks for external events

---

**Last Updated**: 2026-06-17  
**Version**: 1.0  
**Status**: Production Ready ✅
