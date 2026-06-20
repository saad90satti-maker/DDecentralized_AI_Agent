"""
Launch Ghost Engine with Chrome Browser
This script starts the Ghost Engine dashboard and opens Chrome browser.
"""
import asyncio
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


async def launch_chrome_with_ghost_engine():
    """Launch Chrome browser with Ghost Engine dashboard."""
    from playwright.async_api import async_playwright
    
    print("Ghost Engine: Launching Chrome browser...")
    
    # Start the FastAPI server in a subprocess
    server_process = subprocess.Popen(
        [sys.executable, "manager.py"],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    print("Ghost Engine: Starting server on port 8000...")
    time.sleep(3)  # Wait for server to start
    
    # Launch Chrome with Playwright
    p = await async_playwright().start()
    
    # Use Chrome channel if available, otherwise use Chromium
    try:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized"
            ]
        )
    except Exception:
        print("Chrome not found, using Chromium...")
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized"
            ]
        )
    
    # Open the Ghost Engine dashboard
    page = await browser.new_page()
    await page.goto("http://localhost:8000", wait_until="networkidle")
    
    print("Ghost Engine: Chrome browser opened with dashboard!")
    print("  Dashboard URL: http://localhost:8000")
    print("  Press Ctrl+C to stop the server and close browser.")
    
    # Keep the browser open
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await browser.close()
        server_process.terminate()
        print("\nGhost Engine: Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(launch_chrome_with_ghost_engine())
    except KeyboardInterrupt:
        print("\nShutdown requested.")
