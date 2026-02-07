#!/bin/bash
# Setup Computer Use dependencies for Ultron daemon on macOS

set -e

echo "Setting up Computer Use for Ultron daemon..."

# Check macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "Error: Computer Use requires macOS (for screencapture, etc.)"
    echo "On Linux, you'd need Xvfb + xdotool instead."
    exit 1
fi

# Install cliclick (native macOS click tool - lightweight, no accessibility needed for basic ops)
if command -v brew &> /dev/null; then
    if ! command -v cliclick &> /dev/null; then
        echo "Installing cliclick via Homebrew..."
        brew install cliclick
    else
        echo "cliclick already installed"
    fi
else
    echo "Warning: Homebrew not installed. cliclick won't be available."
    echo "Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "Then run: brew install cliclick"
fi

# Install pyautogui as fallback (in the same venv as browser.py if it exists)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    echo "Installing pyautogui in existing venv..."
    source "$VENV_DIR/bin/activate"
    pip install pyautogui Pillow
else
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip
    pip install pyautogui Pillow
fi

echo ""
echo "Setup complete!"
echo ""
echo "IMPORTANT: macOS will ask for Accessibility permissions when"
echo "cliclick or pyautogui first tries to control mouse/keyboard."
echo "Go to: System Settings > Privacy & Security > Accessibility"
echo "and grant permission to Terminal (or whatever runs the daemon)."
echo ""
echo "Test with:"
echo "  python3 $SCRIPT_DIR/computer.py"
echo "  Then type: {\"action\": \"screenshot\"}"
