#!/usr/bin/env python3
"""
Computer Use action executor for Alfred daemon.
Handles screenshot capture, mouse clicks, keyboard input on macOS.
Communicates via JSON over stdin/stdout (same pattern as browser.py).

Uses native macOS tools first (screencapture, cliclick), falls back to pyautogui.
"""

import sys
import json
import asyncio
import base64
import subprocess
import os
import math
import shutil

# Screen dimensions - will be detected on first screenshot
SCREEN_WIDTH = None
SCREEN_HEIGHT = None
SCALE_FACTOR = 1.0

# API constraints from Anthropic docs
MAX_LONG_EDGE = 1568
MAX_TOTAL_PIXELS = 1_150_000


def log(msg):
    print(f"[COMPUTER] {msg}", file=sys.stderr, flush=True)


def has_command(cmd):
    return shutil.which(cmd) is not None


def get_scale_factor(width, height):
    """Calculate scale factor to meet Anthropic API image constraints."""
    long_edge = max(width, height)
    total_pixels = width * height
    long_edge_scale = MAX_LONG_EDGE / long_edge
    total_pixels_scale = math.sqrt(MAX_TOTAL_PIXELS / total_pixels)
    return min(1.0, long_edge_scale, total_pixels_scale)


def detect_screen_size():
    """Detect the main display resolution on macOS."""
    global SCREEN_WIDTH, SCREEN_HEIGHT, SCALE_FACTOR
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10
        )
        import re
        # Look for "Resolution: 1512 x 982" or similar
        match = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", result.stdout)
        if match:
            SCREEN_WIDTH = int(match.group(1))
            SCREEN_HEIGHT = int(match.group(2))
        else:
            # Fallback: try screenresolution tool or defaults
            SCREEN_WIDTH = 1512
            SCREEN_HEIGHT = 982
    except Exception:
        SCREEN_WIDTH = 1512
        SCREEN_HEIGHT = 982

    SCALE_FACTOR = get_scale_factor(SCREEN_WIDTH, SCREEN_HEIGHT)
    log(f"Screen: {SCREEN_WIDTH}x{SCREEN_HEIGHT}, scale_factor: {SCALE_FACTOR:.3f}")


def scale_coordinates_to_screen(x, y):
    """Scale coordinates from Claude's space back to actual screen space."""
    if SCALE_FACTOR < 1.0:
        return int(x / SCALE_FACTOR), int(y / SCALE_FACTOR)
    return x, y


def take_screenshot():
    """Capture screenshot, resize to API constraints, return as base64 PNG."""
    tmp_path = "/tmp/alfred_screenshot.png"
    scaled_path = "/tmp/alfred_screenshot_scaled.png"

    try:
        # Native macOS screencapture (-x = no sound)
        subprocess.run(
            ["screencapture", "-x", "-C", tmp_path],
            timeout=10, check=True
        )
    except Exception as e:
        return None, f"Screenshot failed: {e}"

    # Resize if needed
    if SCALE_FACTOR < 1.0:
        scaled_w = int(SCREEN_WIDTH * SCALE_FACTOR)
        scaled_h = int(SCREEN_HEIGHT * SCALE_FACTOR)
        try:
            subprocess.run(
                ["sips", "--resampleWidth", str(scaled_w), tmp_path, "--out", scaled_path],
                timeout=10, capture_output=True, check=True
            )
            tmp_path = scaled_path
        except Exception:
            pass  # Send original if resize fails

    try:
        with open(tmp_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8"), None
    except Exception as e:
        return None, f"Failed to read screenshot: {e}"


def click_at(x, y, button="left", click_count=1):
    """Click at screen coordinates."""
    screen_x, screen_y = scale_coordinates_to_screen(x, y)
    log(f"click_at: ({x},{y}) -> screen ({screen_x},{screen_y}) button={button} count={click_count}")

    if has_command("cliclick"):
        click_map = {
            ("left", 1): "c",
            ("left", 2): "dc",
            ("left", 3): "tc",
            ("right", 1): "rc",
        }
        action = click_map.get((button, click_count), "c")
        try:
            result = subprocess.run(
                ["cliclick", f"{action}:{screen_x},{screen_y}"],
                timeout=5, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
            log(f"cliclick failed: {result.stderr}")
        except Exception as e:
            log(f"cliclick error: {e}")

    # Fallback: AppleScript for clicking
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
        if result.returncode == 0:
            return True, None
        log(f"AppleScript click failed: {result.stderr}")
    except Exception as e:
        log(f"AppleScript click error: {e}")

    # Fallback: pyautogui
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        if button == "left":
            pyautogui.click(screen_x, screen_y, clicks=click_count)
        elif button == "right":
            pyautogui.rightClick(screen_x, screen_y)
        elif button == "middle":
            pyautogui.middleClick(screen_x, screen_y)
        return True, None
    except Exception as e:
        return False, f"Click failed with all methods: {e}"


def move_mouse(x, y):
    """Move cursor to coordinates."""
    screen_x, screen_y = scale_coordinates_to_screen(x, y)
    log(f"move_mouse: ({x},{y}) -> screen ({screen_x},{screen_y})")

    if has_command("cliclick"):
        try:
            result = subprocess.run(
                ["cliclick", f"m:{screen_x},{screen_y}"],
                timeout=5, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
            log(f"cliclick move failed: {result.stderr}")
        except Exception as e:
            log(f"cliclick move error: {e}")

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.moveTo(screen_x, screen_y)
        return True, None
    except Exception as e:
        return False, f"Mouse move failed: {e}"


def type_text(text):
    """Type text string."""
    if not text:
        return False, "No text to type"
    
    log(f"type_text: '{text[:50]}{'...' if len(text) > 50 else ''}'")
    
    # AppleScript is most reliable for typing on macOS
    try:
        # Escape quotes for AppleScript
        escaped = text.replace('\\', '\\\\').replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=10, capture_output=True, text=True
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
                timeout=10, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True, None
            log(f"cliclick type failed: {result.stderr}")
        except Exception as e:
            log(f"cliclick type error: {e}")

    # Fallback: pyautogui
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.write(text, interval=0.02)
        return True, None
    except Exception as e:
        return False, f"Type failed with all methods: {e}"


def press_key(key_combo):
    """Press key or key combination (e.g., 'Return', 'ctrl+s', 'cmd+a', 'space')."""
    if not key_combo:
        return False, "No key specified"
    
    log(f"press_key called with: '{key_combo}'")
    
    # Use AppleScript as primary method - most reliable on macOS
    # Map key names to AppleScript key codes / names
    applescript_key_map = {
        "return": (36, None), "enter": (36, None),
        "tab": (48, None),
        "escape": (53, None), "esc": (53, None),
        "space": (49, None),
        "delete": (51, None), "backspace": (51, None),
        "up": (126, None), "down": (125, None),
        "left": (123, None), "right": (124, None),
        "home": (115, None), "end": (119, None),
        "page_up": (116, None), "page_down": (121, None),
        "f1": (122, None), "f2": (120, None), "f3": (99, None),
        "f4": (118, None), "f5": (96, None), "f6": (97, None),
        "f7": (98, None), "f8": (100, None), "f9": (101, None),
        "f10": (109, None), "f11": (103, None), "f12": (111, None),
    }
    
    applescript_modifier_map = {
        "ctrl": "control down", "control": "control down",
        "alt": "option down", "option": "option down",
        "cmd": "command down", "command": "command down", "super": "command down",
        "shift": "shift down",
    }
    
    parts = [p.strip().lower() for p in key_combo.split("+")]
    
    # Separate modifiers from the actual key
    modifiers = []
    key = None
    for p in parts:
        if p in applescript_modifier_map:
            modifiers.append(applescript_modifier_map[p])
        else:
            key = p
    
    if not key:
        return False, f"No key found in combo: {key_combo}"
    
    modifier_str = " using {" + ", ".join(modifiers) + "}" if modifiers else ""
    
    # Check if it's a special key (use key code) or a character (use keystroke)
    if key in applescript_key_map:
        key_code, _ = applescript_key_map[key]
        script = f'tell application "System Events" to key code {key_code}{modifier_str}'
    elif len(key) == 1:
        # Single character
        script = f'tell application "System Events" to keystroke "{key}"{modifier_str}'
    else:
        # Try as keystroke anyway
        script = f'tell application "System Events" to keystroke "{key}"{modifier_str}'
    
    try:
        log(f"AppleScript: {script}")
        result = subprocess.run(
            ["osascript", "-e", script],
            timeout=5, capture_output=True, text=True
        )
        if result.returncode == 0:
            return True, None
        else:
            log(f"AppleScript failed: {result.stderr}")
    except Exception as e:
        log(f"AppleScript error: {e}")
    
    # Fallback: pyautogui
    try:
        import pyautogui
        pyautogui.FAILSAFE = False

        pyautogui_map = {
            "ctrl": "ctrl", "control": "ctrl",
            "alt": "alt", "option": "alt",
            "cmd": "command", "command": "command", "super": "command",
            "shift": "shift",
            "return": "enter", "enter": "enter",
            "esc": "escape", "escape": "escape",
            "delete": "backspace", "backspace": "backspace",
            "space": "space", "tab": "tab",
            "up": "up", "down": "down", "left": "left", "right": "right",
        }

        mapped = [pyautogui_map.get(p, p) for p in parts]
        if len(mapped) == 1:
            pyautogui.press(mapped[0])
        else:
            pyautogui.hotkey(*mapped)
        return True, None
    except Exception as e:
        return False, f"Key press failed: {e}"


def scroll_screen(direction="down", amount=3, x=None, y=None):
    """Scroll the screen."""
    # Move to position if specified
    if x is not None and y is not None:
        move_mouse(x, y)

    scroll_amount = amount if direction in ("up", "left") else -amount

    if has_command("cliclick"):
        # cliclick doesn't have scroll, use AppleScript
        try:
            script = f'tell application "System Events" to scroll area 1 by {scroll_amount}'
            subprocess.run(
                ["osascript", "-e", script],
                timeout=5, capture_output=True
            )
            return True, None
        except Exception:
            pass

    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        if direction in ("up", "down"):
            pyautogui.scroll(scroll_amount)
        else:
            pyautogui.hscroll(scroll_amount)
        return True, None
    except Exception as e:
        return False, f"Scroll failed: {e}"


def drag_mouse(start_x, start_y, end_x, end_y):
    """Click and drag."""
    sx, sy = scale_coordinates_to_screen(start_x, start_y)
    ex, ey = scale_coordinates_to_screen(end_x, end_y)

    if has_command("cliclick"):
        try:
            subprocess.run(
                ["cliclick", f"dd:{sx},{sy}", f"du:{ex},{ey}"],
                timeout=10, check=True
            )
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
    """Handle a computer use action from Claude."""
    action = cmd.get("action")

    log(f"Action: {action}")

    try:
        if action == "screenshot":
            img_data, err = take_screenshot()
            if err:
                return {"success": False, "error": err}
            return {
                "success": True,
                "base64_image": img_data,
                "display_width": int(SCREEN_WIDTH * SCALE_FACTOR) if SCALE_FACTOR < 1.0 else SCREEN_WIDTH,
                "display_height": int(SCREEN_HEIGHT * SCALE_FACTOR) if SCALE_FACTOR < 1.0 else SCREEN_HEIGHT,
            }

        elif action == "left_click":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = click_at(coord[0], coord[1], "left")
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "right_click":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = click_at(coord[0], coord[1], "right")
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "double_click":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = click_at(coord[0], coord[1], "left", 2)
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "triple_click":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = click_at(coord[0], coord[1], "left", 3)
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "middle_click":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = click_at(coord[0], coord[1], "middle")
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "mouse_move":
            coord = cmd.get("coordinate", [0, 0])
            ok, err = move_mouse(coord[0], coord[1])
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "type":
            text = cmd.get("text", "")
            ok, err = type_text(text)
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "key":
            key = cmd.get("key", "")
            ok, err = press_key(key)
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "scroll":
            coord = cmd.get("coordinate", [None, None])
            direction = cmd.get("direction", "down")
            amount = cmd.get("amount", 3)
            ok, err = scroll_screen(direction, amount, coord[0], coord[1])
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "left_click_drag":
            start = cmd.get("start_coordinate", [0, 0])
            end = cmd.get("coordinate", [0, 0])
            ok, err = drag_mouse(start[0], start[1], end[0], end[1])
            return {"success": ok, "error": err} if not ok else {"success": True}

        elif action == "wait":
            duration = cmd.get("duration", 1)
            await asyncio.sleep(duration)
            return {"success": True}

        elif action == "ping":
            return {
                "success": True,
                "screen_width": SCREEN_WIDTH,
                "screen_height": SCREEN_HEIGHT,
                "has_cliclick": has_command("cliclick"),
            }

        else:
            return {"success": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        log(f"Error: {e}")
        return {"success": False, "error": str(e)}


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
