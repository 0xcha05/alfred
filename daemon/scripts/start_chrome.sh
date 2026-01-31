#!/bin/bash
# Start Chrome with remote debugging enabled for Alfred browser automation
# This allows Alfred to control your real Chrome with all your logins

PORT=${1:-9222}

echo "Starting Chrome with remote debugging on port $PORT..."
echo ""
echo "⚠️  Keep this terminal open while using browser automation"
echo "   Alfred will control this Chrome instance"
echo ""

# macOS Chrome path
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -f "$CHROME_PATH" ]; then
    echo "Error: Chrome not found at $CHROME_PATH"
    exit 1
fi

# Launch Chrome with debugging
"$CHROME_PATH" \
    --remote-debugging-port=$PORT \
    --no-first-run \
    --no-default-browser-check \
    2>/dev/null

echo "Chrome closed."
