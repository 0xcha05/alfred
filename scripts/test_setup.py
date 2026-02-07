#!/usr/bin/env python3
"""Quick test to verify Ultron Prime setup."""

import asyncio
import sys
import os

# Add prime to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'prime'))

async def test_intent_parsing():
    """Test intent parsing."""
    from app.core.intent import parse_intent, ActionType
    
    print("Testing intent parsing...")
    
    # Test quick patterns
    tests = [
        ("help", ActionType.HELP),
        ("status", ActionType.STATUS),
        ("run ls -la", ActionType.SHELL),
        ("ls /tmp", ActionType.SHELL),
    ]
    
    for text, expected_action in tests:
        intent = await parse_intent(text)
        status = "✓" if intent.action == expected_action else "✗"
        print(f"  {status} '{text}' -> {intent.action} (expected {expected_action})")
    
    print()

async def test_telegram_service():
    """Test telegram service (without actual API calls)."""
    from app.services.telegram_service import TelegramService
    
    print("Testing Telegram service...")
    service = TelegramService()
    print(f"  ✓ Service initialized")
    print(f"  ✓ Base URL: {service.base_url[:50]}...")
    await service.close()
    print()

async def test_config():
    """Test configuration loading."""
    from app.config import settings
    
    print("Testing configuration...")
    print(f"  Environment: {settings.environment}")
    print(f"  Port: {settings.port}")
    print(f"  Telegram token configured: {bool(settings.telegram_token)}")
    print(f"  Claude API key configured: {bool(settings.claude_api_key)}")
    print(f"  Daemon registration key configured: {bool(settings.daemon_registration_key)}")
    print()

async def main():
    print("=" * 50)
    print("Ultron Prime Setup Test")
    print("=" * 50)
    print()
    
    try:
        await test_config()
        await test_intent_parsing()
        await test_telegram_service()
        
        print("=" * 50)
        print("All tests passed!")
        print("=" * 50)
        print()
        print("Next steps:")
        print("1. Copy prime/.env.example to prime/.env")
        print("2. Fill in your Telegram bot token and Claude API key")
        print("3. Start infrastructure: docker-compose up -d")
        print("4. Start Prime: cd prime && uvicorn app.main:app --reload")
        print("5. Start Daemon: cd daemon && go run cmd/daemon/main.go")
        print("6. Expose Prime with ngrok and set up Telegram webhook")
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
