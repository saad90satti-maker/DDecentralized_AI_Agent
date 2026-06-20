# Quick Deploy to Hugging Face Spaces - Step by Step

## In 5 Minutes:

### 1️⃣ Create HF Token
- Go to https://huggingface.co/settings/tokens
- Click "New token" → Select "Write" access → Copy token

### 2️⃣ Create HF Space
- Go to https://huggingface.co/spaces
- Click "Create new Space"
- Name: `Decentralized-AI-Agent`
- SDK: `Docker`
- Keep the **repo ID** (format: `username/Decentralized-AI-Agent`)

### 3️⃣ Add GitHub Secrets
In your GitHub repo settings → Secrets and variables → Actions:

Add 2 secrets:
- `HF_TOKEN` = your token from step 1
- `HF_SPACE_REPO` = your Space ID from step 2

### 4️⃣ Push & Deploy
```bash
cd d:\DDecentralized_AI_Agent
git add .
git commit -m "Deploy to HF Spaces"
git push origin main
```

Watch GitHub Actions run automatically.

### 5️⃣ Access Your Space
When done, go to:
```
https://huggingface.co/spaces/your-username/Decentralized-AI-Agent
```

---

## In HF Space Settings, Add Secrets:

```env
GMAIL_USER=your_email@gmail.com
GMAIL_PASS=your_app_password
HUGGINGFACE_TOKEN=hf_xxxxx
GROQ_API_KEY=gsk_xxxxx
GITHUB_TOKEN=ghp_xxxxx
CLOUDFLARE_TOKEN=cfut_xxxxx
DISCORD_TOKEN=MTxxxxx
DISCORD_CHANNEL_ID=123456789
```

---

## Deployed Features:

✅ Gradio web interface for easy control
✅ Email automation workflows
✅ Browser automation (Playwright)
✅ Command execution
✅ Real-time task dashboard
✅ Public accessibility on internet

---

For detailed troubleshooting, see: `HF_SPACES_DEPLOYMENT.md`
