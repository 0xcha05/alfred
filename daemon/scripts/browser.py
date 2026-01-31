#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Run with: python3 browser.py (or via venv after running setup_browser.sh)
"""
Playwright browser automation wrapper for Alfred daemon.
Communicates via JSON over stdin/stdout.

Commands:
- launch: Start browser
- goto: Navigate to URL
- click: Click element by selector
- type: Type text into element
- get_text: Get text from element
- get_content: Get page content
- screenshot: Take screenshot
- evaluate: Run JavaScript
- wait: Wait for selector
- close: Close browser
"""

import sys
import json
import asyncio
import base64
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

# Global state
browser: Browser = None
context: BrowserContext = None
page: Page = None
playwright = None


async def handle_command(cmd: dict) -> dict:
    """Handle a single command."""
    global browser, context, page, playwright
    
    action = cmd.get("action")
    
    try:
        if action == "launch":
            headless = cmd.get("headless", False)
            use_real_chrome = cmd.get("use_real_chrome", True)  # Default to real Chrome
            chrome_port = cmd.get("chrome_port", 9222)
            
            playwright = await async_playwright().start()
            
            if use_real_chrome:
                # Connect to user's real Chrome (must be launched with --remote-debugging-port)
                try:
                    browser = await playwright.chromium.connect_over_cdp(f"http://localhost:{chrome_port}")
                    contexts = browser.contexts
                    if contexts:
                        context = contexts[0]
                        pages = context.pages
                        if pages:
                            page = pages[0]
                        else:
                            page = await context.new_page()
                    else:
                        context = await browser.new_context()
                        page = await context.new_page()
                    return {"success": True, "message": f"Connected to real Chrome on port {chrome_port}", "mode": "real_chrome"}
                except Exception as e:
                    # Chrome not running with debug port - provide instructions
                    return {
                        "success": False,
                        "error": f"Could not connect to Chrome: {e}",
                        "instructions": f"Start Chrome with: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port={chrome_port}",
                        "alternative": "Or use launch with use_real_chrome=false for a fresh browser"
                    }
            else:
                # Use Playwright's own browser (fresh, no logins)
                browser = await playwright.chromium.launch(headless=headless)
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                )
                page = await context.new_page()
                return {"success": True, "message": "Fresh browser launched", "mode": "playwright"}
        
        elif action == "goto":
            url = cmd.get("url")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)  # Let JS settle
            return {"success": True, "url": page.url, "title": await page.title()}
        
        elif action == "click":
            selector = cmd.get("selector")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            await page.click(selector, timeout=10000)
            await asyncio.sleep(0.5)
            return {"success": True, "clicked": selector}
        
        elif action == "type":
            selector = cmd.get("selector")
            text = cmd.get("text")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            await page.fill(selector, text, timeout=10000)
            return {"success": True, "typed": text}
        
        elif action == "get_text":
            selector = cmd.get("selector")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            element = await page.query_selector(selector)
            if element:
                text = await element.text_content()
                return {"success": True, "text": text.strip() if text else ""}
            return {"success": False, "error": f"Element not found: {selector}"}
        
        elif action == "get_content":
            if not page:
                return {"success": False, "error": "Browser not launched"}
            # Get readable text content
            content = await page.evaluate("""() => {
                // Remove script and style elements
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('script, style, noscript').forEach(el => el.remove());
                return clone.innerText;
            }""")
            # Truncate if too long
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            return {"success": True, "content": content, "url": page.url, "title": await page.title()}
        
        elif action == "screenshot":
            if not page:
                return {"success": False, "error": "Browser not launched"}
            path = cmd.get("path", "/tmp/screenshot.png")
            await page.screenshot(path=path, full_page=cmd.get("full_page", False))
            return {"success": True, "path": path}
        
        elif action == "evaluate":
            script = cmd.get("script")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            result = await page.evaluate(script)
            return {"success": True, "result": result}
        
        elif action == "wait":
            selector = cmd.get("selector")
            timeout = cmd.get("timeout", 10000)
            if not page:
                return {"success": False, "error": "Browser not launched"}
            await page.wait_for_selector(selector, timeout=timeout)
            return {"success": True, "found": selector}
        
        elif action == "wait_idle":
            if not page:
                return {"success": False, "error": "Browser not launched"}
            await page.wait_for_load_state("networkidle", timeout=30000)
            return {"success": True, "message": "Page idle"}
        
        elif action == "scroll":
            direction = cmd.get("direction", "down")
            amount = cmd.get("amount", 500)
            if not page:
                return {"success": False, "error": "Browser not launched"}
            if direction == "down":
                await page.evaluate(f"window.scrollBy(0, {amount})")
            else:
                await page.evaluate(f"window.scrollBy(0, -{amount})")
            await asyncio.sleep(0.3)
            return {"success": True, "scrolled": direction}
        
        elif action == "get_elements":
            selector = cmd.get("selector")
            if not page:
                return {"success": False, "error": "Browser not launched"}
            elements = await page.query_selector_all(selector)
            texts = []
            for el in elements[:20]:  # Limit to 20
                text = await el.text_content()
                if text:
                    texts.append(text.strip())
            return {"success": True, "elements": texts, "count": len(elements)}
        
        elif action == "close":
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
            browser = None
            context = None
            page = None
            playwright = None
            return {"success": True, "message": "Browser closed"}
        
        elif action == "ping":
            return {"success": True, "status": "running", "has_browser": browser is not None}
        
        else:
            return {"success": False, "error": f"Unknown action: {action}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


async def main():
    """Main loop - read commands from stdin, write responses to stdout."""
    # Signal ready
    print(json.dumps({"ready": True}), flush=True)
    
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    
    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            
            line = line.decode().strip()
            if not line:
                continue
            
            cmd = json.loads(line)
            result = await handle_command(cmd)
            print(json.dumps(result), flush=True)
            
        except json.JSONDecodeError as e:
            print(json.dumps({"success": False, "error": f"Invalid JSON: {e}"}), flush=True)
        except Exception as e:
            print(json.dumps({"success": False, "error": f"Error: {e}"}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
