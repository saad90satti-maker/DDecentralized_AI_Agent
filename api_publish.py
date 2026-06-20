"""YouTube upload via UI, then publish via API (fast - no UI processing wait)"""
import asyncio, json, time, re
from pathlib import Path
from playwright.async_api import async_playwright
import httpx

async def api_publish():
    print("="*60, flush=True)
    print("  GHOST ENGINE - API PUBLISH v1")
    print("="*60, flush=True)

    BASE = "https://studio.youtube.com/youtubei/v1"
    report = {}

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="C:\\Users\\zafar\\AppData\\Local\\Google\\Chrome\\User Data\\Default",
            headless=False,
            args=["--window-position=0,0"],
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ── 1. Navigate to Studio ──
        await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print("[1] Channel dashboard", flush=True)

        # ── 2. Extract cookies for API auth ──
        cookies = await ctx.cookies()
        sapisid = next((c['value'] for c in cookies if c['name'] == 'SAPISID'), None)
        if not sapisid:
            print("  SAPISID cookie not found! Trying PSAPISID...", flush=True)
            sapisid = next((c['value'] for c in cookies if c['name'] == 'PSAPISID'), None)
        print(f"  SAPISID: {sapisid[:20] if sapisid else 'None'}...", flush=True)

        # ── 3. Get fresh session info ──
        session_info = await page.evaluate("""() => {
            const meta = document.querySelector('meta[itemprop="channelId"]');
            const script = document.querySelector('script[nonce]');
            return {
                channelId: meta ? meta.content : '',
                url: location.href,
            };
        }""")
        print(f"  Channel: {session_info['channelId'][:20] if session_info.get('channelId') else '?'}", flush=True)

        # ── 4. Upload video ──
        print("[2] Opening upload dialog...", flush=True)
        create_btn = page.locator("ytcp-button#create-icon, [aria-label='Create'], ytcp-button:has-text('Create')").first
        await create_btn.click()
        await asyncio.sleep(2)

        upload_btn = page.locator("ytcp-ve:has-text('Upload videos')").first
        await upload_btn.click()
        await asyncio.sleep(2)

        file_path = str(Path(__file__).resolve().parent / "hermes_demo_video.mp4")
        file_chooser = page.locator("input[type='file']").first
        await file_chooser.set_input_files(file_path)
        print(f"[3] Uploading: {Path(file_path).name}", flush=True)

        # ── 5. Wait briefly for upload + title input ──
        try:
            await page.locator("#title-textbox, #textbox").first.wait_for(state="visible", timeout=120000)
            print("[4] Upload processed, title available", flush=True)
        except:
            print("[4] Upload processing timed out", flush=True)

        title_text = f"Hermes AI Agent - API Publish {int(time.time())}"
        try:
            ti = page.locator("#title-textbox, #textbox").first
            await ti.fill("")
            await ti.type(title_text, delay=10)
            print(f"[5] Title: {title_text}", flush=True)
        except:
            pass

        await asyncio.sleep(5)

        # ── 6. Get video ID from the page ──
        video_id = await page.evaluate("""() => {
            // Try to find video ID from URL or data attributes
            const d = document.querySelector('ytcp-uploads-dialog');
            if (!d) return '';
            const text = d.textContent || '';
            // Look for video ID pattern
            const match = text.match(/[\\?&]v=([a-zA-Z0-9_-]{11})/);
            return match ? match[1] : '';
        }""")
        print(f"  Video ID from dialog: {video_id or 'not found'}", flush=True)

        # Also try to find video ID via cookies/state
        # Navigate to video manager quickly
        await page.goto("https://studio.youtube.com/videos", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(5)

        # Get video ID from URL
        current_url = page.url
        print(f"  Current URL: {current_url}", flush=True)

        # ── 7. List recent videos via API ──
        print("[6] Fetching video list via API...", flush=True)
        sapisidhash = None
        if sapisid:
            # Build SAPISID hash for Authorization header
            from datetime import datetime
            import hashlib
            timestamp = int(datetime.now().timestamp())
            sapisidhash = hashlib.sha1(f"{timestamp} {sapisid} https://studio.youtube.com".encode()).hexdigest()

        # Try to get videos via YouTubei API
        headers = {
            "Content-Type": "application/json",
            "Origin": "https://studio.youtube.com",
            "X-Goog-Request-Time": str(int(time.time())),
            "X-Goog-Visitor-Id": await page.evaluate("() => document.cookie.match(/VISITOR_INFO1_LIVE=([^;]+)/)?.[1] || ''"),
        }
        if sapisid and sapisidhash:
            headers["Authorization"] = f"SAPISIDHASH {timestamp}_{sapisidhash}"
            headers["X-Goog-AuthUser"] = "0"

        # Add cookies to httpx client
        cookie_dict = {c['name']: c['value'] for c in cookies}
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        headers["Cookie"] = cookie_header

        print(f"  API Auth header: {headers.get('Authorization','')[:40]}...", flush=True)

        # Try to get video list
        try:
            async with httpx.AsyncClient() as client:
                # Fetch video list from creator page
                payload = {"context": {"client": {"clientName": "WEB", "clientVersion": "2.0"}}}
                resp = await client.post(
                    f"{BASE}/creator/list_creator?prettyPrint=false",
                    headers=headers, json=payload, timeout=30
                )
                print(f"  API status: {resp.status_code}", flush=True)
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  Response keys: {list(data.keys())[:10]}", flush=True)
                else:
                    print(f"  Error: {resp.text[:500]}", flush=True)
        except Exception as e:
            print(f"  API error: {e}", flush=True)

        # ── 8. Take screenshot ──
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\api_publish.png")
        print("[7] Screenshot saved", flush=True)

    print("\nDone!", flush=True)

if __name__ == "__main__":
    asyncio.run(api_publish())
