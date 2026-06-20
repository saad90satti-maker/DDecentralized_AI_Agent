"""YouTube upload + publish via API: capture videoId from network, set to public via youtubei API."""
import asyncio, json, time, hashlib
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
import httpx

async def publish_v5():
    print("="*60)
    print("  GHOST ENGINE - YOUTUBE PUBLISH v5 (network capture + API)")
    print("="*60)

    report = {"start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    video_id = None
    sapisid = None

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="C:\\Users\\zafar\\AppData\\Local\\Google\\Chrome\\User Data\\Default",
            headless=False,
            args=["--window-position=0,0"],
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ── 1. Capture upload response for video ID ──
        all_responses = []
        async def on_response(resp):
            nonlocal video_id
            url = resp.url
            all_responses.append(url)
            if resp.status == 200 and ("upload" in url.lower() or "video" in url.lower()):
                if "youtubei/v1" in url:
                    try:
                        body = await resp.json()
                        vid = body.get("videoId") or body.get("id") or \
                              body.get("encryptedVideoId") or body.get("externalVideoId")
                        if vid:
                            video_id = vid
                            print(f"  [NET] Captured videoId: {video_id} from {url[:80]}", flush=True)
                    except:
                        pass
        page.on("response", on_response)

        # ── 2. Go to Studio dashboard and capture real API auth headers ──
        real_auth = {}
        async def capture_headers(resp):
            if "list_creator_videos" in resp.url and resp.status == 200:
                req = resp.request
                for h in ['authorization', 'x-goog-authuser', 'x-goog-pageid', 'x-goog-visitor-id']:
                    real_auth[h] = req.headers.get(h, '')
                print(f"  Captured real API auth headers!", flush=True)
                for k, v in real_auth.items():
                    print(f"    {k}: {v[:80]}", flush=True)
        page.on("response", capture_headers)

        try:
            await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)
            print("[1] Channel dashboard", flush=True)
        except Exception as e:
            print(f"  Goto error (continuing): {e}", flush=True)

        # Extract cookies for API auth
        cookies = await ctx.cookies()
        sapisid = next((c['value'] for c in cookies if c['name'] == 'SAPISID'), None) or \
                  next((c['value'] for c in cookies if c['name'] == '__Secure-3PSAPISID'), None)
        print(f"  SAPISID: {sapisid[:15] if sapisid else 'None'}...", flush=True)

        # ── 4. Open upload dialog ──
        print("[2] Opening upload...", flush=True)
        create_btn = page.locator("ytcp-button#create-icon, [aria-label='Create'], ytcp-button:has-text('Create')").first
        await create_btn.click()
        await asyncio.sleep(2)
        upload_btn = page.locator("ytcp-ve:has-text('Upload videos')").first
        await upload_btn.click()
        await asyncio.sleep(2)

        # ── 5. Upload file ──
        file_path = str(Path(__file__).resolve().parent / "hermes_demo_video.mp4")
        file_input = page.locator("input[type='file']").first
        await file_input.set_input_files(file_path)
        print(f"[3] Uploaded: {Path(file_path).name}", flush=True)

        # ── 6. Wait for title input ──
        try:
            await page.locator("#title-textbox, #textbox").first.wait_for(state="visible", timeout=120000)
            print("[4] Upload processed!", flush=True)
        except:
            print("[4] Upload processing timed out", flush=True)

        # ── 7. Fill title ──
        title_text = f"Hermes AI Agent - v5 {int(time.time())}"
        try:
            ti = page.locator("#title-textbox, #textbox").first
            await ti.fill("")
            await ti.type(title_text, delay=10)
            print(f"[5] Title: {title_text}", flush=True)
            report["title"] = title_text
        except:
            pass

        await asyncio.sleep(5)

        # ── 8. Try to get video ID from dialog state ──
        if not video_id:
            video_id = await page.evaluate("""() => {
                const d = document.querySelector('ytcp-uploads-dialog');
                if (!d) return '';
                // Check for video ID in data attributes
                const all = d.querySelectorAll('*');
                for (const el of all) {
                    if (el.id && el.id.length === 11) return el.id;
                    const vid = el.getAttribute('video-id') || el.getAttribute('videoid');
                    if (vid) return vid;
                }
                // Check URL params
                const match = d.innerHTML.match(/[\\?&]v=([a-zA-Z0-9_-]{11})/);
                return match ? match[1] : '';
            }""")
            print(f"  Video ID from dialog: {video_id or 'not found'}", flush=True)

        # ── 9. Close dialog (wait a bit for processing) ──
        print("[6] Closing upload dialog...", flush=True)
        await asyncio.sleep(10)  # brief wait for processing
        try:
            close_btn = page.locator("#ytcp-uploads-dialog-close-button").first
            if await close_btn.is_visible(timeout=2000):
                await close_btn.click()
            else:
                await page.keyboard.press("Escape")
        except:
            await page.keyboard.press("Escape")
        await asyncio.sleep(2)

        # ── 10. Publish via API (using real captured auth headers) ──
        published = False
        print("[7] Fetching video list via browser API...", flush=True)

        # Build headers from the captured real request
        api_headers = {'Content-Type': 'application/json'}
        if real_auth.get('authorization'):
            api_headers['authorization'] = real_auth['authorization']
        if real_auth.get('x-goog-authuser'):
            api_headers['X-Goog-AuthUser'] = real_auth['x-goog-authuser']
        if real_auth.get('x-goog-pageid'):
            api_headers['X-Goog-PageId'] = real_auth['x-goog-pageid']

        api_result = await page.evaluate(f"""async () => {{
            const base = 'https://studio.youtube.com/youtubei/v1';
            const headers = {json.dumps(api_headers)};

            // 1. List videos
            const listResp = await fetch(base + '/creator/list_creator_videos?alt=json', {{
                method: 'POST', headers,
                body: JSON.stringify({{context: {{client: {{clientName: 'WEB', clientVersion: '2.0'}}}}}})
            }});
            if (!listResp.ok) return {{error: 'list: ' + listResp.status + ' ' + (await listResp.text()).slice(0,100)}};

            const listData = await listResp.json();

            // Find first video
            let videos = listData.videos || listData.items || [];
            for (const key of Object.keys(listData)) {{
                if (Array.isArray(listData[key]) && listData[key].length > 0) {{
                    videos = listData[key];
                    break;
                }}
            }}

            if (videos.length === 0) return {{error: 'no videos', dataKeys: Object.keys(listData)}};

            const first = videos[0];
            const vid = first.encryptedVideoId || first.videoId || first.id;
            console.log('First video:', JSON.stringify(first).slice(0, 500));
            if (!vid) return {{error: 'no videoId', first: JSON.stringify(first).slice(0, 300)}};

            // 2. Set to Public
            const updatePayload = {{
                context: {{client: {{clientName: 'WEB', clientVersion: '2.0'}}}},
                encryptedVideoId: vid,
                newPrivacy: 'PUBLIC',
            }};

            for (const ep of ['creator/update_creator_video', 'creator/update_video_metadata',
                              'creator/bulk_update_video_metadata',
                              'video_manager/update_creator_video']) {{
                const ur = await fetch(base + '/' + ep + '?alt=json', {{
                    method: 'POST', headers,
                    body: JSON.stringify(updatePayload)
                }});
                const body = await ur.text();
                if (ur.ok) return {{success: true, videoId: vid, endpoint: ep}};
                console.log(ep + ':', ur.status, body.slice(0, 200));
            }}
            return {{error: 'all endpoints failed', videoId: vid}};
        }}""")
        print(f"  API result: {json.dumps(api_result, indent=2)[:500]}", flush=True)
        if api_result.get('success'):
            video_id = api_result['videoId']
            published = True
        else:
            if api_result.get('videoId'):
                video_id = api_result['videoId']
            print(f"  API failed: {api_result.get('error')}", flush=True)

        # ── 11. Screenshot ──
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\publish_v5_final.png")
        print("[8] Screenshot saved", flush=True)

        report["video_id"] = video_id or "NOT_FOUND"
        report["publish"] = "PUBLISHED" if published else "API_FAILED"
        report["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["final"] = "SUCCESS" if published else "PARTIAL"

        rp = Path(__file__).resolve().parent / "agent_data" / "publish_v5_report.json"
        with open(rp, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Report: {rp}")
        print(f"  Status: {report['final']}")

    return report

if __name__ == "__main__":
    asyncio.run(publish_v5())
