"""Reply all to visible inbox Gmail messages with 'Nice to hear from you'"""
import asyncio, os, sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
from playwright.async_api import async_playwright

REPLY_TEXT = "Nice to hear from you"
CHROME_PROFILE = os.getenv(
    "BROWSER_USER_DATA_DIR",
    os.path.expanduser("~/AppData/Local/Google/Chrome/User Data/Default")
)

async def main():
    print("Opening Gmail...")
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            headless=False,
            args=["--window-position=0,0"],
            viewport={"width": 1400, "height": 1000},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        await page.goto("https://mail.google.com", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        if "signin" in page.url:
            input("Login required. Press Enter after logging in...")
            await asyncio.sleep(3)

        # Count emails
        email_rows = page.locator("tr.zA")
        total = await email_rows.count()
        print(f"Found {total} visible emails")

        replied = 0
        for i in range(total):
            try:
                row = email_rows.nth(i)
                # Scroll into view
                await row.scroll_into_view_if_needed()
                await asyncio.sleep(0.5)

                # Get sender/subject safely
                try:
                    sender = (await row.locator(".yW, .yX").first.text_content(timeout=1000) or "?").strip()
                    subject = (await row.locator(".y6, .bog").first.text_content(timeout=1000) or "?").strip()
                except:
                    sender, subject = "?", "?"

                # Skip if already checked (contains "Re:" in subject)
                if subject.startswith("Re:"):
                    print(f"  [{i+1}] Skipping (already replied): {sender}")
                    continue

                print(f"\n[{i+1}/{total}] {sender}: {subject[:50]}")

                # Click the email
                await row.click()
                await asyncio.sleep(2)

                # Try to find Reply All button using multiple selectors
                reply_btn = page.locator(
                    "[aria-label='Reply all'], "
                    "[data-tooltip='Reply all'], "
                    "div.aCy, "
                    "div.amn, "
                    "[aria-label*='Reply all'], "
                    "img[alt='Reply all']"
                ).first

                if await reply_btn.is_visible(timeout=2000):
                    await reply_btn.click()
                    await asyncio.sleep(2)

                    # Find the reply textbox
                    reply_box = page.locator(
                        "[aria-label='Reply'], "
                        "[role='textbox'][contenteditable='true'], "
                        "div.editable, "
                        "[aria-label^='Reply']"
                    ).first

                    if await reply_box.is_visible(timeout=3000):
                        await reply_box.fill("")
                        await reply_box.type(REPLY_TEXT, delay=5)
                        await asyncio.sleep(1)

                        # Send button
                        send_btn = page.locator(
                            "[aria-label='Send'], "
                            "div.T-I.J-J5-Ji.aoO, "
                            "div[role='button'][data-tooltip='Send']"
                        ).first

                        if await send_btn.is_visible(timeout=2000):
                            await send_btn.click()
                            replied += 1
                            print(f"  -> Sent! ({replied} total)")
                            await asyncio.sleep(2)
                        else:
                            print("  Send btn not found")
                    else:
                        print("  Reply box not found")
                else:
                    print("  No Reply All (likely automated notification)")

                # Back to inbox
                back = page.locator("[aria-label='Back to Inbox'], [data-tooltip='Back to Inbox']").first
                if await back.is_visible(timeout=2000):
                    await back.click()
                    await asyncio.sleep(1.5)
                else:
                    # Keyboard shortcut: u
                    await page.keyboard.press("u")
                    await asyncio.sleep(2)

            except UnicodeEncodeError:
                # Skip encoding issues in console
                continue
            except Exception as e:
                err = str(e)[:80]
                print(f"  Error: {err}")
                try:
                    await page.keyboard.press("u")
                    await asyncio.sleep(2)
                except:
                    pass

        print(f"\nDone! Replied to {replied} emails")
        await page.screenshot(path="D:\\DDecentralized_AI_Agent\\agent_data\\gmail_done.png")

asyncio.run(main())
