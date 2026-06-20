# Ghost Engine - Chrome Browser Launchers

This folder contains scripts to launch the Ghost Engine dashboard in Chrome browser.

## Quick Start

### Option 1: Simple Launch (Recommended)
```bash
python quick_launch.py
```
This will:
1. Start the Ghost Engine server
2. Open Chrome (or default browser) with the dashboard

### Option 2: Advanced Launch
```bash
python launch_chrome.py
```
This will:
1. Start the Ghost Engine server
2. Launch Chrome using Playwright with automation features
3. Keep the browser open with the dashboard

## Prerequisites

1. **Chrome Browser** (optional but recommended)
   - Download from: https://www.google.com/chrome/
   - If not installed, the scripts will use Chromium or default browser

2. **Playwright** (for advanced features)
   ```bash
   pip install playwright
   playwright install
   ```

## Features

### Dashboard Features
- **Status Monitor**: View service status and pending tasks
- **Command Execution**: Run shell commands directly
- **Task Queue**: Queue tasks for async execution
- **Hermes Integration**: Send text to Hermes for analysis
- **Deployment**: Deploy to cloud platforms (Render, HuggingFace)

### Browser Automation
The Ghost Engine includes a browser agent that can:
- Navigate to websites
- Fill forms automatically
- Take screenshots
- Execute JavaScript
- Claim airdrops (crypto)

## Usage Examples

### Basic Usage
```bash
# Start the dashboard in Chrome
python quick_launch.py
```

### With Browser Automation
```python
import asyncio
from browser_agent import BrowserAgent

async def main():
    async with BrowserAgent(headless=False) as agent:
        await agent.goto("https://example.com")
        await agent.screenshot("screenshot.png")
        print("Screenshot saved!")

asyncio.run(main())
```

## Troubleshooting

### Chrome Not Found
If Chrome is not installed:
1. Install Chrome from https://www.google.com/chrome/
2. Or use the fallback options in the scripts

### Server Won't Start
1. Check if port 8000 is already in use
2. Kill any existing processes on port 8000:
   ```bash
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F
   ```

### Playwright Issues
If you encounter Playwright errors:
```bash
pip install playwright
playwright install
```

## Files

- `quick_launch.py` - Simple launcher using default browser
- `launch_chrome.py` - Advanced launcher using Playwright
- `scripts/launch_cdp.py` - Chrome DevTools Protocol launcher
- `scripts/check_status.py` - Check YouTube upload status
