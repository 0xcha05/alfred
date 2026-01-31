#!/bin/bash
# Setup Playwright for Alfred browser automation

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Setting up Playwright for Alfred daemon..."

# Check if Python3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python3 is required but not installed."
    exit 1
fi

# Create virtual environment if it doesn't exist
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install requirements
echo "Installing Playwright..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$SCRIPT_DIR/requirements.txt"

# Install Playwright browsers
echo "Installing Playwright browsers (this may take a while)..."
playwright install chromium

echo ""
echo "✓ Playwright setup complete!"
echo ""
echo "The daemon will automatically use the browser script at:"
echo "  $SCRIPT_DIR/browser.py"
echo ""
echo "Make sure to rebuild the daemon after setup:"
echo "  cd $SCRIPT_DIR/../ && go build -o daemon ./cmd/daemon"
