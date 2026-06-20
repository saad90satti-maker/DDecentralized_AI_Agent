"""Test original production_pipeline selectors for YouTube upload."""
import asyncio
import base64
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
PROFILE = str(Path.home() / "AppData/Local/Google/Chrome/User Data/Default")
VIDEO = Path("D:/DDecentralized_AI_Agent/hermes_demo_video.mp4")


async def test_original():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    ctx = await p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome",
        args=["--no-sandbox"], no_viewport=True
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    await page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(5)
    print(f"Page: {await page.title()}", flush=True)

    body = await page.text_content("body") or ""
    if "Sign in" in body[:1000]:
        print("LOGIN REQUIRED", flush=True)
        return

    print("Session ACTIVE", flush=True)

    # Try Create with ytcp-button#create-icon
    print("Clicking Create...", flush=True)
    try:
        btn = page.locator("ytcp-button#create-icon").first
        if await btn.is_visible(timeout=3000):
            await btn.click()
            print("  via ytcp-button#create-icon", flush=True)
        else:
            await page.locator("[aria-label='Create']").first.click()
            print("  via [aria-label='Create']", flush=True)
    except Exception as e:
        print(f"  Create error: {e}", flush=True)
    await asyncio.sleep(3)

    # Upload videos - try WITHOUT force=True first
    print("Clicking Upload videos...", flush=True)
    try:
        up = page.locator("ytcp-ve:has-text('Upload videos')").first
        if await up.is_visible(timeout=3000):
            await up.click()
            print("  via ytcp-ve (original)", flush=True)
        else:
            up2 = page.locator("text=Upload videos").first
            await up2.click()
            print("  via text", flush=True)
    except Exception as e:
        print(f"  Upload error: {e}", flush=True)
    await asyncio.sleep(3)

    # File input search
    print("Searching for file inputs...", flush=True)
    fi = page.locator("input[type='file']").first
    try:
        await fi.wait_for(state="attached", timeout=15000)
        print("File input FOUND!", flush=True)
        await fi.set_input_files(str(VIDEO))
        print("VIDEO UPLOADED VIA SET_INPUT_FILES!", flush=True)
    except Exception as e:
        print(f"File input not attached: {e}", flush=True)
        # Deep scan for file inputs
        result = await page.evaluate("""() => {
            function deepFind(root, depth) {
                if (!root || depth > 30) return [];
                let r = [];
                try {
                    if (root.shadowRoot) {
                        let fi = root.shadowRoot.querySelectorAll('input[type="file"]');
                        fi.forEach(el => r.push({tag: el.tagName, id: el.id, cl: (el.className||'').slice(0,30), visible: el.offsetParent !== null, source: 'shadow', path: depth}));
                        r = r.concat(deepFind(root.shadowRoot, depth+1));
                    }
                    if (root.querySelectorAll) {
                        let fi = root.querySelectorAll('input[type="file"]');
                        fi.forEach(el => r.push({tag: el.tagName, id: el.id, cl: (el.className||'').slice(0,30), visible: el.offsetParent !== null, source: 'light', path: depth}));
                    }
                    for (let c of (root.children || [])) {
                        if (c && c.tagName) r = r.concat(deepFind(c, depth+1));
                    }
                } catch(e) {}
                return r;
            }
            let all = deepFind(document, 0);
            let seen = new Set();
            let unique = all.filter(x => { let k = x.id || x.tag + Math.random(); if(seen.has(k)) return false; seen.add(k); return true; });
            return JSON.stringify(unique);
        }""")
        print(f"Deep scan: {result[:500]}", flush=True)

        # Try uploading via JS File constructor + DataTransfer
        if VIDEO.exists():
            with open(VIDEO, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            upload_result = await page.evaluate(f"""async (b64data) => {{
                try {{
                    const resp = await fetch('data:video/mp4;base64,' + b64data);
                    const blob = await resp.blob();
                    const file = new File([blob], 'hermes_demo_video.mp4', {{ type: 'video/mp4' }});
                    const dt = new DataTransfer();
                    dt.items.add(file);

                    // Method 1: Find drop zone
                    const dz = document.querySelector('ytcp-uploads-file-picker');
                    if (dz) {{
                        dz.dispatchEvent(new DragEvent('drop', {{ dataTransfer: dt, bubbles: true, cancelable: true }}));
                        return 'drop_zone';
                    }}

                    // Method 2: Find any file input and set files
                    function deepSetFiles(root) {{
                        if (!root) return false;
                        let handled = false;
                        try {{
                            if (root.shadowRoot) {{
                                let fi = root.shadowRoot.querySelector('input[type=\"file\"]');
                                if (fi) {{ fi.files = dt.files; fi.dispatchEvent(new Event('change', {{ bubbles: true }})); return true; }}
                                handled = deepSetFiles(root.shadowRoot);
                            }}
                            if (!handled && root.querySelectorAll) {{
                                let fi = root.querySelector('input[type=\"file\"]');
                                if (fi && fi !== root) {{ 
                                    try {{ fi.files = dt.files; fi.dispatchEvent(new Event('change', {{ bubbles: true }})); return true; }} catch(e) {{ }}
                                }}
                            }}
                            for (let c of (root.children || [])) {{ if (c.tagName && !handled) handled = deepSetFiles(c); }}
                        }} catch(e) {{ }}
                        return handled;
                    }}
                    if (deepSetFiles(document.documentElement)) return 'deep_set_success';

                    // Method 3: Create new input and dispatch
                    const inp = document.createElement('input');
                    inp.type = 'file'; inp.style.display = 'none';
                    document.body.appendChild(inp);
                    Object.defineProperty(inp, 'files', {{ value: dt.files, writable: false }});
                    inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return 'new_input_created:' + inp.files.length;
                }} catch(e) {{ return 'error:' + e.message; }}
            }}""", b64)
            print(f"JS upload: {upload_result}", flush=True)
            await asyncio.sleep(5)

    # Check page state
    await page.screenshot(path="D:/DDecentralized_AI_Agent/agent_data/original_test.png")
    print("Screenshot saved", flush=True)
    await ctx.close()
    await p.stop()


asyncio.run(test_original())
