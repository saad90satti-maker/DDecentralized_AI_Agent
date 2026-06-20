"""
Ghost Engine - Chrome Browser Launcher
Launch the Ghost Engine dashboard in Chrome browser.
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path


def check_chrome_installed():
    """Check if Chrome is installed."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
            __import__("os").getenv("USERNAME", "")
        ),
    ]
    for path in chrome_paths:
        if Path(path).exists():
            return True
    return False


def launch_chrome_with_dashboard():
    """Launch Chrome with Ghost Engine dashboard."""
    print("=" * 60)
    print("Ghost Engine - Chrome Browser Launcher")
    print("=" * 60)
    
    # Check if Chrome is installed
    if not check_chrome_installed():
        print("\n[WARNING] Chrome browser not found!")
        print("Please install Chrome from: https://www.google.com/chrome/")
        print("Or the script will use Chromium as fallback.\n")
    
    # Start the FastAPI server
    print("\n[1/3] Starting Ghost Engine server...")
    server_process = subprocess.Popen(
        [sys.executable, "manager.py"],
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    print("[2/3] Waiting for server to initialize...")
    time.sleep(4)
    
    # Check if server is running
    try:
        import requests
        response = requests.get("http://localhost:8000/api/status", timeout=5)
        if response.status_code == 200:
            print("[3/3] Server is running successfully!")
        else:
            print("[WARNING] Server responded with status code:", response.status_code)
    except Exception as e:
        print("[WARNING] Could not verify server status:", str(e))
    
    # Launch Chrome
    print("\n" + "=" * 60)
    print("Launching Chrome browser...")
    print("=" * 60)
    
    # Try to launch Chrome with Playwright
    try:
        from playwright.async_api import async_playwright
        
        async def launch():
            p = await async_playwright().start()
            
            # Try Chrome first, fallback to Chromium
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
                print("Using Chrome browser")
            except Exception:
                print("Chrome not available, using Chromium...")
                browser = await p.chromium.launch(
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--start-maximized"
                    ]
                )
            
            # Open dashboard
            page = await browser.new_page()
            await page.goto("http://localhost:8000", wait_until="networkidle")
            
            print("\n" + "=" * 60)
            print("Ghost Engine Dashboard is now open in Chrome!")
            print("=" * 60)
            print("\nDashboard URL: http://localhost:8000")
            print("\nAvailable Features:")
            print("  - View service status and pending tasks")
            print("  - Execute shell commands")
            print("  - Send tasks to Hermes for analysis")
            print("  - Queue tasks for async execution")
            print("  - Deploy to cloud platforms")
            print("\nPress Ctrl+C in this terminal to stop the server.")
            print("=" * 60)
            
            # Keep browser open
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                await browser.close()
        
        asyncio.run(launch())
        
    except ImportError:
        print("\n[ERROR] Playwright not installed!")
        print("Install with: pip install playwright && playwright install")
        print("\nAlternative: Open Chrome manually and navigate to:")
        print("  http://localhost:8000")
        input("\nPress Enter after you've opened Chrome...")
    
    except Exception as e:
        print(f"\n[ERROR] Failed to launch browser: {e}")
        print("\nPlease open Chrome manually and navigate to:")
        print("  http://localhost:8000")
        input("\nPress Enter after you've opened Chrome...")
    
    finally:
        # Cleanup
        try:
            server_process.terminate()
            server_process.wait(timeout=5)
        except:
            server_process.kill()
        print("\nGhost Engine server stopped.")


if __name__ == "__main__":
    try:
        launch_chrome_with_dashboard()
    except KeyboardInterrupt:
        print("\n\nShutdown requested.")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
