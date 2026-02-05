#!/usr/bin/env python3
"""
Computer Use action executor for Alfred daemon (macOS).
Based on Anthropic's official documentation and reference implementation.

Uses Anthropic's recommended approach:
- Fixed API dimensions (1024x768) that match what we tell Claude
- Screenshots resized to those exact dimensions
- Claude's coordinates scaled back to actual screen pixels

macOS-specific tools:
- screencapture for screenshots
- sips for image resizing
- cliclick for mouse/keyboard (brew install cliclick)
- osascript (AppleScript) as fallback
"""

import sys
import json
import asyncio
import base64
import subprocess
import shutil
import re

# The dimensions we tell Claude about (must match brain.py's display_width_px/display_height_px)
# Anthropic's quickstart recommends 1024x768
API_WIDTH = 1024
API_HEIGHT = 768

# Actual screen dimensions - detected on startup
SCREEN_WIDTH = None
SCREEN_HEIGHT = None

# Scale factor: API -> Screen
SCALE_X = 1.0
SCALE_Y = 1.0


def log(msg):
    print(f"[COMPUTER] {msg}", file=sys.stderr, flush=True)


def has_command(cmd):
    return shutil.which(cmd) is not None


def detect_screen_size():
    """Detect the LOGICAL (point) resolution on macOS and compute scale factors.
    
    CRITICAL: On Retina Macs, screencapture gives PIXEL dimensions (e.g. 2880x1800)
    but cliclick uses POINT dimensions (e.g. 1440x900). We MUST use point dimensions
    for coordinate scaling, otherwise clicks will be off by 2x.
    
    Priority:
    1. Finder desktop bounds (most reliable for logical resolution)
    2. Python Quartz (CGDisplayPixelsWide - gives logical)
    3. system_profiler "UI Looks Like" line
    4. system_profiler Resolution / 2 if Retina
    5. Default 1440x900
    """
    global SCREEN_WIDTH, SCREEN_HEIGHT, SCALE_X, SCALE_Y

    # Method 1: Finder desktop bounds (gives LOGICAL resolution directly)
    try:
        result = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Output is like "0, 0, 1440, 900"
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) == 4:
                SCREEN_WIDTH = int(parts[2])
                SCREEN_HEIGHT = int(parts[3])
                log(f"Detected LOGICAL screen from Finder: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
    except Exception as e:
        log(f"Finder bounds failed: {e}")

    # Method 2: Python Quartz (CGDisplayPixelsWide gives logical resolution)
    if not SCREEN_WIDTH:
        try:
            script = 'import Quartz; m=Quartz.CGMainDisplayID(); print(f"{Quartz.CGDisplayPixelsWide(m)}x{Quartz.CGDisplayPixelsHigh(m)}")'
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split("x")
                if len(parts) == 2:
                    SCREEN_WIDTH = int(parts[0])
                    SCREEN_HEIGHT = int(parts[1])
                    log(f"Detected LOGICAL screen from Quartz: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        except Exception as e:
            log(f"Quartz detection failed: {e}")

    # Method 3: system_profiler (can be pixel OR logical depending on macOS version)
    if not SCREEN_WIDTH:
        try:
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True, timeout=10
            )
            is_retina = "Retina" in result.stdout
            
            # Try "UI Looks Like" first (this IS logical)
            ui_match = re.search(r"UI Looks Like:\s*(\d+)\s*x\s*(\d+)", result.stdout)
            if ui_match:
                SCREEN_WIDTH = int(ui_match.group(1))
                SCREEN_HEIGHT = int(ui_match.group(2))
                log(f"Detected LOGICAL screen from 'UI Looks Like': {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
            else:
                # Fall back to Resolution line
                res_match = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", result.stdout)
                if res_match:
                    w = int(res_match.group(1))
                    h = int(res_match.group(2))
                    if is_retina:
                        # system_profiler shows PHYSICAL resolution on Retina; divide by 2
                        SCREEN_WIDTH = w // 2
                        SCREEN_HEIGHT = h // 2
                        log(f"Detected screen from profiler (Retina, halved): {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
                    else:
                        SCREEN_WIDTH = w
                        SCREEN_HEIGHT = h
                        log(f"Detected screen from profiler: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")
        except Exception as e:
            log(f"system_profiler failed: {e}")

    # Default fallback
    if not SCREEN_WIDTH:
        SCREEN_WIDTH = 1440
        SCREEN_HEIGHT = 900
        log(f"Using default screen: {SCREEN_WIDTH}x{SCREEN_HEIGHT}")

    # Compute scale factors: how to convert API coords -> screen (point) coords
    # Claude sends coords in API_WIDTH x API_HEIGHT space
    # cliclick operates in SCREEN_WIDTH x SCREEN_HEIGHT point space
    SCALE_X = SCREEN_WIDTH / API_WIDTH
    SCALE_Y = SCREEN_HEIGHT / API_HEIGHT
    log(f"Scale factors: x={SCALE_X:.3f}, y={SCALE_Y:.3f}")
    log(f"API dimensions: {API_WIDTH}x{API_HEIGHT}, Screen (logical): {SCREEN_WIDTH}x{SCREEN_HEIGHT}")


def scale_api_to_screen(x, y):
    """Scale coordinates FROM Claude's API space TO actual screen pixels."""
    screen_x = round(x * SCALE_X)
    screen_y = round(y * SCALE_Y)
    return screen_x, screen_y


def scale_screen_to_api(x, y):
    """Scale coordinates FROM screen pixels TO Claude's API space."""
    api_x = round(x / SCALE_X)
    api_y = round(y / SCALE_Y)
    return api_x, api_y


def take_screenshot():
    """Capture screenshot, resize to API dimensions, return as base64 PNG.
    
    Per Anthropic docs: we resize screenshots to match the display_width_px
    and display_height_px we declared in the tool definition. This way Claude's
    coordinates match exactly what it sees.
    """
    tmp_path = "/tmp/alfred_screenshot.png"
    resized_path = "/tmp/alfred_screenshot_resized.png"

    try:
        subprocess.run(
            ["screencapture", "-x", "-C", tmp_path],
            timeout=10, check=True, capture_output=True
        )
    except Exception as e:
        return None, f"Screenshot failed: {e}"

    # Always resize to API dimensions so Claude's coordinate space matches
    try:
        subprocess.run(
            ["sips", "--resampleWidth", str(API_WIDTH),
             "--resampleHeight", str(API_HEIGHT),
             tmp_path, "--out", resized_path],
            timeout=10, capture_output=True, check=True
        )
        target_path = resized_path
    except Exception as e:
        log(f"Resize failed (sending original - COORDINATES WILL BE WRONG): {e}")
        target_path = tmp_path

    try:
        with open(target_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8"), None
    except Exception as e:
        return None, f"Failed to read screenshot: {e}"


def cliclick_move_and_click(screen_x, screen_y, click_type="c"):
    """Move mouse and click using cliclick."""
    try:
        result = subprocess.run(
            ["cliclick", f"{click_type}:{screen_x},{screen_y}"],
            timeout=5, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, None
        return False, f"cliclick: {result.stderr}"
    except Exception as e:
        return False, str(e)


def applescript_click(screen_x, screen_y):
    """Click using AppleScript (fallback)."""
    try:
        script = f'''
        tell application "System Events"
            click at {{{screen_x}, {screen_y}}}
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=5, capture_output=True, text=True
        )
        return result.returncode == 0, result.stderr
    except Exception as e:
        return False, str(e)


def do_click(x, y, button="left", count=1):
    """Click at API coordinates. Handles scaling."""
    screen_x, screen_y = scale_api_to_screen(x, y)
    log(f"click: api({x},{y}) -> screen({screen_x},{screen_y}) {button} x{count}")

    if has_command("cliclick"):
        click_map = {
            ("left", 1): "c", ("left", 2): "dc", ("left", 3): "tc",
            ("right", 1): "rc",
        }
        ct = click_map.get((button, count), "c")
        ok, err = cliclick_move_and_click(screen_x, screen_y, ct)
        if ok:
            return True, None
        log(f"cliclick failed: {err}")

    # Fallback
    ok, err = applescript_click(screen_x, screen_y)
    if ok:
        return True, None

    return False, f"All click methods failed for ({screen_x},{screen_y})"


def do_move(x, y):
    """Move mouse to API coordinates."""
    screen_x, screen_y = scale_api_to_screen(x, y)
    log(f"move: api({x},{y}) -> screen({screen_x},{screen_y})")

    if has_command("cliclick"):
        try:
            result = subprocess.run(
                ["cliclick", f"m:{screen_x},{screen_y}"],
                timeout=5, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(screen_x, screen_y)
        return True, None
    except Exception as e:
        return False, f"Move failed: {e}"


def do_key(text):
    """Press key combo. `text` is in xdotool format (e.g., 'Return', 'ctrl+a', 'space')."""
    if not text:
        return False, "No key specified"
    log(f"key: '{text}'")

    # Map xdotool key names to AppleScript key codes
    key_code_map = {
        "return": 36, "enter": 36, "Return": 36,
        "tab": 48, "Tab": 48,
        "escape": 53, "Escape": 53,
        "space": 49,
        "delete": 51, "backspace": 51, "BackSpace": 51,
        "up": 126, "Up": 126,
        "down": 125, "Down": 125,
        "left": 123, "Left": 123,
        "right": 124, "Right": 124,
        "home": 115, "Home": 115,
        "end": 119, "End": 119,
        "page_up": 116, "Prior": 116, "Page_Up": 116,
        "page_down": 121, "Next": 121, "Page_Down": 121,
        "f1": 122, "F1": 122, "f2": 120, "F2": 120,
        "f3": 99, "F3": 99, "f4": 118, "F4": 118,
        "f5": 96, "F5": 96, "f6": 97, "F6": 97,
    }

    modifier_map = {
        "ctrl": "control down", "control": "control down", "Control_L": "control down",
        "alt": "option down", "option": "option down", "Alt_L": "option down",
        "cmd": "command down", "command": "command down", "super": "command down",
        "Super_L": "command down", "Meta_L": "command down",
        "shift": "shift down", "Shift_L": "shift down",
    }

    # Handle combos like "ctrl+a", "cmd+shift+s", or single keys like "Return"
    # Claude may send xdotool-style names
    parts = [p.strip() for p in text.replace(" ", "+").split("+")]

    modifiers = []
    key = None
    for p in parts:
        if p.lower() in modifier_map or p in modifier_map:
            modifiers.append(modifier_map.get(p.lower(), modifier_map.get(p, "")))
        else:
            key = p

    if not key:
        return False, f"No key found in: {text}"

    modifier_str = " using {" + ", ".join(modifiers) + "}" if modifiers else ""

    # Check if it maps to a key code
    code = key_code_map.get(key) or key_code_map.get(key.lower())
    if code:
        script = f'tell application "System Events" to key code {code}{modifier_str}'
    elif len(key) == 1:
        script = f'tell application "System Events" to keystroke "{key}"{modifier_str}'
    else:
        # Try as keystroke
        script = f'tell application "System Events" to keystroke "{key}"{modifier_str}'

    log(f"AppleScript: {script}")
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=5, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, None
        log(f"AppleScript key failed: {result.stderr}")
        return False, f"Key press failed: {result.stderr}"
    except Exception as e:
        return False, f"Key press error: {e}"


def do_type(text):
    """Type text string."""
    if not text:
        return False, "No text to type"
    log(f"type: '{text[:80]}{'...' if len(text) > 80 else ''}'")

    # AppleScript keystroke for typing
    try:
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=15, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, None
        log(f"AppleScript type failed: {result.stderr}")
    except Exception as e:
        log(f"AppleScript type error: {e}")

    # Fallback: cliclick
    if has_command("cliclick"):
        try:
            result = subprocess.run(
                ["cliclick", f"t:{text}"],
                timeout=15, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
        except Exception:
            pass

    return False, "Type failed with all methods"


def do_scroll(direction, amount, coordinate=None):
    """Scroll the screen."""
    if coordinate:
        do_move(coordinate[0], coordinate[1])

    log(f"scroll: {direction} x{amount}")

    # AppleScript scrolling
    try:
        if direction in ("up", "down"):
            delta = amount if direction == "up" else -amount
            script = f'''
            tell application "System Events"
                scroll area 1 by {delta}
            end tell
            '''
        else:
            # Horizontal scroll not well supported via AppleScript
            delta = amount if direction == "right" else -amount
            script = f'''
            tell application "System Events"
                scroll area 1 by {delta} horizontally
            end tell
            '''
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
        return True, None
    except Exception:
        pass

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        clicks = amount if direction in ("up", "left") else -amount
        if direction in ("up", "down"):
            pyautogui.scroll(clicks)
        else:
            pyautogui.hscroll(clicks)
        return True, None
    except Exception as e:
        return False, f"Scroll failed: {e}"


def do_drag(start_coord, end_coord):
    """Click and drag from start to end."""
    sx, sy = scale_api_to_screen(start_coord[0], start_coord[1])
    ex, ey = scale_api_to_screen(end_coord[0], end_coord[1])
    log(f"drag: ({sx},{sy}) -> ({ex},{ey})")

    if has_command("cliclick"):
        try:
            result = subprocess.run(
                ["cliclick", f"dd:{sx},{sy}", f"du:{ex},{ey}"],
                timeout=10, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(sx, sy)
        pyautogui.drag(ex - sx, ey - sy, duration=0.5)
        return True, None
    except Exception as e:
        return False, f"Drag failed: {e}"


async def handle_command(cmd: dict) -> dict:
    """Handle a computer use action from Claude.
    
    IMPORTANT: Per Anthropic's reference implementation, most actions return a
    screenshot AFTER the action completes, so Claude can see the result.
    """
    action = cmd.get("action")
    text = cmd.get("text")
    coordinate = cmd.get("coordinate")
    start_coordinate = cmd.get("start_coordinate")
    scroll_direction = cmd.get("scroll_direction")
    scroll_amount = cmd.get("scroll_amount", 3)
    duration = cmd.get("duration", 1)

    log(f"Action: {action}, text={text}, coord={coordinate}")

    try:
        # === Screenshot (no post-screenshot needed) ===
        if action == "screenshot":
            img_data, err = take_screenshot()
            if err:
                return {"success": False, "error": err}
            return {
                "success": True,
                "base64_image": img_data,
                "display_width": API_WIDTH,
                "display_height": API_HEIGHT,
            }

        # === Click actions ===
        elif action in ("left_click", "right_click", "double_click", "triple_click", "middle_click"):
            if coordinate:
                button = "right" if action == "right_click" else "middle" if action == "middle_click" else "left"
                count = 2 if action == "double_click" else 3 if action == "triple_click" else 1
                ok, err = do_click(coordinate[0], coordinate[1], button, count)
            else:
                # Click at current mouse position
                if has_command("cliclick"):
                    result = subprocess.run(["cliclick", "p:."], capture_output=True, text=True, timeout=5)
                    pos = result.stdout.strip() if result.returncode == 0 else "0,0"
                    ct = {"left_click": "c", "right_click": "rc", "double_click": "dc", "triple_click": "tc", "middle_click": "c"}.get(action, "c")
                    r = subprocess.run(["cliclick", f"{ct}:{pos}"], capture_output=True, text=True, timeout=5)
                    ok, err = (r.returncode == 0), (r.stderr if r.returncode != 0 else None)
                else:
                    ok, err = False, "No coordinate and no cliclick"
            return await _result_with_screenshot(ok, err)

        # === Mouse move ===
        elif action == "mouse_move":
            if not coordinate:
                return {"success": False, "error": "coordinate required for mouse_move"}
            ok, err = do_move(coordinate[0], coordinate[1])
            return await _result_with_screenshot(ok, err)

        # === Left click drag ===
        elif action == "left_click_drag":
            if not start_coordinate or not coordinate:
                return {"success": False, "error": "start_coordinate and coordinate required"}
            ok, err = do_drag(start_coordinate, coordinate)
            return await _result_with_screenshot(ok, err)

        # === Key press (text field has the key name, per Anthropic spec) ===
        elif action == "key":
            ok, err = do_key(text)
            return await _result_with_screenshot(ok, err)

        # === Type text ===
        elif action == "type":
            ok, err = do_type(text)
            return await _result_with_screenshot(ok, err)

        # === Scroll ===
        elif action == "scroll":
            ok, err = do_scroll(
                scroll_direction or "down",
                scroll_amount or 3,
                coordinate
            )
            return await _result_with_screenshot(ok, err)

        # === Wait ===
        elif action == "wait":
            await asyncio.sleep(duration)
            img_data, _ = take_screenshot()
            return {"success": True, "base64_image": img_data}

        # === Cursor position (no screenshot) ===
        elif action == "cursor_position":
            if has_command("cliclick"):
                result = subprocess.run(["cliclick", "p:."], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    parts = result.stdout.strip().split(",")
                    if len(parts) == 2:
                        sx, sy = int(parts[0]), int(parts[1])
                        ax, ay = scale_screen_to_api(sx, sy)
                        return {"success": True, "x": ax, "y": ay}
            return {"success": False, "error": "Could not get cursor position"}

        # === Ping ===
        elif action == "ping":
            return {
                "success": True,
                "screen_width": SCREEN_WIDTH,
                "screen_height": SCREEN_HEIGHT,
                "api_width": API_WIDTH,
                "api_height": API_HEIGHT,
                "scale_x": SCALE_X,
                "scale_y": SCALE_Y,
                "has_cliclick": has_command("cliclick"),
            }

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        log(f"Error: {e}")
        return {"success": False, "error": str(e)}


async def _result_with_screenshot(ok, err):
    """Return result with a follow-up screenshot (so Claude can see what happened).
    
    Per Anthropic's reference: after every action, take a screenshot so Claude
    can verify the result visually. This is critical for reliable computer use.
    """
    await asyncio.sleep(0.5)  # Let UI settle before screenshotting
    img_data, img_err = take_screenshot()
    result = {"success": ok}
    if err:
        result["error"] = err
    if img_data:
        result["base64_image"] = img_data
    elif img_err:
        result["screenshot_error"] = img_err
    return result


async def main():
    """Main loop - read commands from stdin, write responses to stdout."""
    detect_screen_size()

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
