#!/usr/bin/env python3
"""
Simple test to verify Prime is running and accepting daemon connections.
Run this on your MacBook to test connectivity to EC2.
"""

import socket
import json
import struct
import sys
import os

def send_message(sock, msg):
    """Send a JSON message with length prefix."""
    data = json.dumps(msg).encode('utf-8')
    length = struct.pack('>I', len(data))
    sock.sendall(length + data)

def recv_message(sock):
    """Receive a JSON message with length prefix."""
    length_data = sock.recv(4)
    if not length_data:
        return None
    length = struct.unpack('>I', length_data)[0]
    data = sock.recv(length)
    return json.loads(data.decode('utf-8'))

def test_connection(host, port, reg_key):
    """Test connection to Prime."""
    print(f"\n🔌 Connecting to Prime at {host}:{port}...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        print("✓ TCP connection established")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nTroubleshooting:")
        print("  1. Is Prime running on EC2?")
        print("  2. Is port 50051 open in EC2 security group?")
        print(f"  3. Can you ping {host}?")
        return False
    
    try:
        # Send registration
        print("\n📝 Sending registration...")
        send_message(sock, {
            "type": "registration",
            "registration_key": reg_key,
            "name": "test-client",
            "hostname": socket.gethostname(),
            "capabilities": ["shell", "files"],
            "is_soul_daemon": False,
        })
        
        # Wait for ack
        response = recv_message(sock)
        if response and response.get("success"):
            daemon_id = response.get("daemon_id")
            print(f"✓ Registered as {daemon_id}")
            print(f"  Message: {response.get('message')}")
            
            # Send a heartbeat
            print("\n💓 Sending heartbeat...")
            send_message(sock, {
                "type": "heartbeat",
                "daemon_id": daemon_id,
                "cpu_percent": 10.5,
                "memory_percent": 45.2,
            })
            print("✓ Heartbeat sent")
            
            print("\n🎉 All tests passed! Connection is working.")
            return True
        else:
            print(f"✗ Registration failed: {response}")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False
    finally:
        sock.close()

if __name__ == "__main__":
    # Get connection details
    host = os.environ.get("PRIME_HOST", "localhost")
    port = int(os.environ.get("PRIME_PORT", "50051"))
    reg_key = os.environ.get("DAEMON_REGISTRATION_KEY", "")
    
    if len(sys.argv) > 1:
        host = sys.argv[1]
    if len(sys.argv) > 2:
        port = int(sys.argv[2])
    if len(sys.argv) > 3:
        reg_key = sys.argv[3]
    
    if not reg_key:
        print("Usage: python test_connection.py <host> <port> <registration_key>")
        print("   or: PRIME_HOST=x PRIME_PORT=y DAEMON_REGISTRATION_KEY=z python test_connection.py")
        sys.exit(1)
    
    success = test_connection(host, port, reg_key)
    sys.exit(0 if success else 1)
