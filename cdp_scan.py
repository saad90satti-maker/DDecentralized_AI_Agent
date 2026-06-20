"""
Ghost Media Engine: CDP Browser State Scanner
Connects to Chrome DevTools Protocol on port 9222
Scans: open pages, cookies, local storage, network endpoints
"""
import json
import urllib.request
import time

CDP_HOST = "http://127.0.0.1:9222"

def cdp_send(ws_url: str, method: str, params: dict = None) -> dict:
    """Send CDP command via HTTP (simplified — uses /json/new protocol)."""
    import websocket
    ws = websocket.create_connection(ws_url)
    msg_id = 1
    cmd = json.dumps({"id": msg_id, "method": method, "params": params or {}})
    ws.send(cmd)
    response = ws.recv()
    ws.close()
    return json.loads(response)


def get_targets() -> list:
    resp = urllib.request.urlopen(f"{CDP_HOST}/json")
    return json.loads(resp.read())


def get_version() -> dict:
    resp = urllib.request.urlopen(f"{CDP_HOST}/json/version")
    return json.loads(resp.read())


def scan_cookies(ws_url: str) -> list:
    """Get cookies from the browser via Network.getAllCookies."""
    import websocket
    ws = websocket.create_connection(ws_url, timeout=10)
    cmd = json.dumps({"id": 1, "method": "Network.getAllCookies"})
    ws.send(cmd)
    raw = ws.recv()
    ws.close()
    data = json.loads(raw)
    return data.get("result", {}).get("cookies", [])


def scan_cookies_all_targets(targets: list) -> dict:
    """Scan cookies across all unique targets."""
    all_cookies = {}
    seen = set()
    for t in targets:
        ws_url = t.get("webSocketDebuggerUrl", "")
        if not ws_url or ws_url in seen:
            continue
        seen.add(ws_url)
        try:
            cookies = scan_cookies(ws_url)
            for c in cookies:
                domain = c.get("domain", "unknown")
                name = c.get("name", "")
                if domain not in all_cookies:
                    all_cookies[domain] = []
                all_cookies[domain].append({
                    "name": name,
                    "value": c.get("value", "")[:60],
                    "secure": c.get("secure", False),
                    "httpOnly": c.get("httpOnly", False),
                    "session": c.get("session", True),
                })
        except Exception as e:
            pass
    return all_cookies


print("=" * 60)
print("  GHOST MEDIA ENGINE - CDP BROWSER SCAN")
print("=" * 60)

# Browser Version
try:
    ver = get_version()
    print(f"\n  Browser: {ver.get('Browser', '?')}")
    print(f"  Protocol: {ver.get('Protocol-Version', '?')}")
    print(f"  User Agent: {ver.get('User-Agent', '?')[:80]}")
except Exception as e:
    print(f"  Version check: {e}")

# Open Targets
targets = get_targets()
print(f"\n  Open Pages/Tabs: {len(targets)}")
for t in targets:
    title = t.get("title", "?")[:70]
    url = t.get("url", "?")[:80]
    ws = t.get("webSocketDebuggerUrl", "no-ws")[:40]
    print(f"    [{title}]")
    print(f"      URL: {url}")
    print(f"      WS:  {ws}")

# Cookie Scan
print(f"\n>>> Scanning cookies across all targets...")
cookies_by_domain = scan_cookies_all_targets(targets)
print(f"  Domains with cookies: {len(cookies_by_domain)}")
for domain, cookies in sorted(cookies_by_domain.items()):
    names = ", ".join(c["name"] for c in cookies[:8])
    extra = f" ... (+{len(cookies)-8})" if len(cookies) > 8 else ""
    print(f"    {domain}: {names}{extra}")

# Identify logged-in services
print(f"\n>>> Active Sessions Detected:")
known_services = {
    "google.com": "Google",
    "youtube.com": "YouTube",
    "github.com": "GitHub",
    "facebook.com": "Facebook",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "linkedin.com": "LinkedIn",
    "reddit.com": "Reddit",
    "discord.com": "Discord",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "huggingface.co": "HuggingFace",
    "medium.com": "Medium",
    "notion.so": "Notion",
    "netflix.com": "Netflix",
    "amazon.com": "Amazon",
    "spotify.com": "Spotify",
}
sessions_found = []
for domain in cookies_by_domain:
    for key, label in known_services.items():
        if key in domain:
            sessions_found.append((domain, label))
            break
if sessions_found:
    for domain, label in sorted(set(sessions_found)):
        cookies = cookies_by_domain[domain]
        has_session_cookie = any("session" in c["name"].lower() or "token" in c["name"].lower() or "auth" in c["name"].lower() for c in cookies)
        print(f"    [ACTIVE] {label} ({domain}) - session_cookie: {has_session_cookie}")
else:
    print(f"    No known logged-in services detected. Checking all domains...")

# Save full results
output = {
    "browser": ver.get("Browser", "?"),
    "open_targets": [{"title": t["title"], "url": t["url"]} for t in targets],
    "cookies_by_domain": {d: len(cs) for d, cs in cookies_by_domain.items()},
    "active_sessions": [label for _, label in set(sessions_found)],
}
with open("D:\\DDecentralized_AI_Agent\\agent_data\\cdp_scan.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\n  Full scan saved to agent_data/cdp_scan.json")
print("=" * 60)
