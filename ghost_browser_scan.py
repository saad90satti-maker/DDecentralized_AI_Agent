"""
Ghost Media Engine: Full Browser State Scanner
Uses Playwright (same persistent profile) to scan:
  - Open tabs (from Chrome session restore)
  - All cookies across all domains
  - Local/session storage
  - Network API endpoints from active pages
  - Active logged-in sessions
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PROFILE_PATH = os.getenv(
    "BROWSER_USER_DATA_DIR",
    str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
)


async def scan_browser():
    from playwright.async_api import async_playwright

    print("=" * 60)
    print("  GHOST MEDIA ENGINE - BROWSER STATE SCAN")
    print(f"  Profile: {PROFILE_PATH}")
    print("=" * 60)

    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_PATH,
        headless=False,
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        no_viewport=False,
    )

    results = {
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "profile": PROFILE_PATH,
        "pages": [],
        "cookies_by_domain": {},
        "active_sessions": [],
        "api_endpoints": [],
        "storage": [],
    }

    # --- PAGES ---
    pages = context.pages
    print(f"\n  Open Pages: {len(pages)}")
    for i, page in enumerate(pages):
        try:
            title = await page.title()
            url = page.url
            print(f"  [{i}] {title[:60]}")
            print(f"       URL: {url[:100]}")

            page_info = {"title": title, "url": url, "cookies": [], "storage": [], "api_calls": []}

            # Page cookies
            try:
                cookies = await context.cookies()
                domain_cookies = {}
                for c in cookies:
                    d = c.get("domain", "unknown")
                    if d not in domain_cookies:
                        domain_cookies[d] = []
                    domain_cookies[d].append(c["name"])
                    page_info["cookies"].append(c["name"])
                for d, names in domain_cookies.items():
                    if d not in results["cookies_by_domain"]:
                        results["cookies_by_domain"][d] = []
                    results["cookies_by_domain"][d].extend(names)
            except Exception as e:
                print(f"       Cookie error: {e}")

            # Local storage
            try:
                storage_data = await page.evaluate("""() => {
                    const items = {};
                    for (let i = 0; i < localStorage.length; i++) {
                        const k = localStorage.key(i);
                        items[k] = (localStorage.getItem(k) || '').substring(0, 100);
                    }
                    return items;
                }""")
                if storage_data:
                    keys = list(storage_data.keys())[:10]
                    page_info["storage"] = keys
                    results["storage"].append({"page": url[:60], "keys": keys})
                    print(f"       LocalStorage keys: {len(storage_data)}")
            except:
                pass

            # Session storage
            try:
                session_data = await page.evaluate("""() => {
                    const items = {};
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const k = sessionStorage.key(i);
                        items[k] = (sessionStorage.getItem(k) || '').substring(0, 100);
                    }
                    return items;
                }""")
                if session_data:
                    print(f"       SessionStorage keys: {len(session_data)}")
            except:
                pass

            results["pages"].append(page_info)
        except Exception as e:
            print(f"  [{i}] ERROR: {e}")

    # --- ALL COOKIES ---
    print(f"\n>>> Full Cookie Scan ({len(results['cookies_by_domain'])} domains)")
    for domain, cookies in sorted(results["cookies_by_domain"].items()):
        unique = list(set(cookies))
        print(f"    {domain}: {', '.join(unique[:8])}{' ...' if len(unique) > 8 else ''}")

    # --- ACTIVE SESSIONS ---
    known_services = {
        "google.com": "Google", "youtube.com": "YouTube", "github.com": "GitHub",
        "facebook.com": "Facebook", "twitter.com": "Twitter/X", "x.com": "Twitter/X",
        "linkedin.com": "LinkedIn", "reddit.com": "Reddit", "discord.com": "Discord",
        "openai.com": "OpenAI", "anthropic.com": "Anthropic/Claude",
        "huggingface.co": "HuggingFace", "medium.com": "Medium",
        "notion.so": "Notion", "netflix.com": "Netflix",
        "amazon.com": "Amazon", "spotify.com": "Spotify",
        "chatgpt.com": "ChatGPT", "claude.ai": "Claude",
        "perplexity.ai": "Perplexity", "bing.com": "Bing",
        "stackoverflow.com": "StackOverflow", "gitlab.com": "GitLab",
        "docker.com": "Docker", "npmjs.com": "npm",
        "pypi.org": "PyPI", "vercel.com": "Vercel",
        "heroku.com": "Heroku", "digitalocean.com": "DigitalOcean",
        "cloudflare.com": "Cloudflare",
    }
    print(f"\n>>> Detected Active Sessions:")
    for domain in results["cookies_by_domain"]:
        for key, label in known_services.items():
            if key in domain:
                results["active_sessions"].append(label)
                print(f"    [ACTIVE] {label} ({domain})")
                break
    if not results["active_sessions"]:
        print(f"    No known services detected. Domains: {list(results['cookies_by_domain'].keys())}")

    # --- API ENDPOINT DETECTION (via network monitoring on a fresh navigation) ---
    print(f"\n>>> API Endpoint Discovery (monitoring network requests)...")
    api_patterns = ["/api/", "/v1/", "/v2/", "/graphql", "/rest/", "/oauth/", "/token", "/auth"]
    discovered = set()
    try:
        if pages:
            page = pages[0]
            # Monitor network requests for API patterns
            async def capture_request(request):
                url = request.url
                if any(p in url.lower() for p in api_patterns):
                    discovered.add(url[:150])
            page.on("request", capture_request)
            # Refresh page to trigger network calls
            await page.reload(timeout=10000)
            await asyncio.sleep(3)
            page.remove_listener("request", capture_request)
    except Exception as e:
        print(f"    Network monitor: {e}")

    if discovered:
        results["api_endpoints"] = sorted(discovered)[:20]
        for ep in sorted(discovered)[:20]:
            print(f"    {ep}")
    else:
        print(f"    No API endpoints discovered (fresh page had no API calls)")

    # --- SAVE ---
    output_path = Path(__file__).resolve().parent / "agent_data" / "ghost_scan.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Full scan saved to {output_path}")

    await context.close()
    await p.stop()
    print("=" * 60)
    return results


if __name__ == "__main__":
    asyncio.run(scan_browser())
