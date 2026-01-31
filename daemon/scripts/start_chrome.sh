#!/bin/bash
# Start a browser with remote debugging for Alfred
# Uses Firefox by default so you can keep using Chrome normally

PORT=${1:-9222}
BROWSER=${2:-firefox}

if [ "$BROWSER" = "firefox" ]; then
    FIREFOX_PATH="/Applications/Firefox.app/Contents/MacOS/firefox"
    
    if [ ! -f "$FIREFOX_PATH" ]; then
        echo "Firefox not found. Install it or use: ./start_chrome.sh 9222 chrome"
        exit 1
    fi
    
    # Create a fresh profile for Alfred
    ALFRED_PROFILE="/tmp/alfred-firefox-profile"
    mkdir -p "$ALFRED_PROFILE"
    
    echo "🦊 Starting Firefox for Alfred on port $PORT..."
    echo ""
    echo "   You can keep using Chrome normally!"
    echo "   Alfred will control this Firefox window."
    echo ""
    echo "⚠️  Keep this terminal open while using browser automation"
    echo ""
    
    # Firefox uses --remote-debugging-port
    "$FIREFOX_PATH" \
        --remote-debugging-port=$PORT \
        --profile "$ALFRED_PROFILE" \
        --new-instance \
        2>/dev/null
    
    echo "Firefox closed."

else
    # Chrome mode (requires killing existing Chrome)
    CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    if [ ! -f "$CHROME_PATH" ]; then
        echo "Chrome not found at $CHROME_PATH"
        exit 1
    fi
    
    if pgrep -f "Google Chrome" > /dev/null; then
        echo "⚠️  Chrome is already running!"
        read -p "Kill Chrome and restart with debugging? (y/n): " choice
        if [ "$choice" = "y" ] || [ "$choice" = "Y" ]; then
            pkill -f "Google Chrome"
            sleep 2
        else
            exit 1
        fi
    fi
    
    TEMP_PROFILE="/tmp/alfred-chrome-profile"
    mkdir -p "$TEMP_PROFILE"
    
    echo "Starting Chrome for Alfred on port $PORT..."
    echo "⚠️  Keep this terminal open"
    echo ""
    
    "$CHROME_PATH" \
        --remote-debugging-port=$PORT \
        --user-data-dir="$TEMP_PROFILE" \
        --no-first-run \
        2>/dev/null
    
    echo "Chrome closed."
fi
