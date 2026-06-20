"""
Quick Chrome Launcher for Ghost Engine
Simple script to open Chrome with Ghost Engine dashboard.
"""
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def find_chrome():
    """Find Chrome executable."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
            __import__("os").getenv("USERNAME", "")
        ),
    ]
    for path in chrome_paths:
        if Path(path).exists():
            return path
    return None


def main():
    print("Ghost Engine - Quick Chrome Launcher")
    print("=" * 50)
    
    # Start server
    print("\nStarting Ghost Engine server...")
    server = subprocess.Popen(
        [sys.executable, "manager.py"],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    time.sleep(3)
    print("Server started on http://localhost:8000")
    
    # Find and launch Chrome
    chrome_path = find_chrome()
    if chrome_path:
        print(f"\nFound Chrome at: {chrome_path}")
        print("Launching Chrome with Ghost Engine dashboard...")
        subprocess.Popen([chrome_path, "http://localhost:8000"])
    else:
        print("\nChrome not found, opening in default browser...")
        webbrowser.open("http://localhost:8000")
    
    print("\n" + "=" * 50)
    print("Ghost Engine is now running!")
    print("Dashboard: http://localhost:8000")
    print("Press Ctrl+C to stop the server.")
    print("=" * 50)
    
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\n\nStopping server...")
        server.terminate()
        server.wait(timeout=5)
        print("Server stopped.")


if __name__ == "__main__":
    main()
