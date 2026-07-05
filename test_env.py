"""
Run this in your crypto-trading-bot folder to diagnose .env issues.
python test_env.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

key    = os.getenv("BINANCE_API_KEY")
secret = os.getenv("BINANCE_API_SECRET")

print("=" * 50)
print("  .env Diagnostic Tool")
print("=" * 50)

if key:
    print(f"✅ BINANCE_API_KEY    found: {key[:6]}...{key[-4:]} (len={len(key)})")
else:
    print("❌ BINANCE_API_KEY    NOT FOUND")

if secret:
    print(f"✅ BINANCE_API_SECRET found: {secret[:6]}...{secret[-4:]} (len={len(secret)})")
else:
    print("❌ BINANCE_API_SECRET NOT FOUND")

print()

# Check for common mistakes
if key:
    if " " in key:
        print("⚠️  WARNING: BINANCE_API_KEY has spaces in it — remove them")
    if key.startswith('"') or key.startswith("'"):
        print("⚠️  WARNING: BINANCE_API_KEY has quotes around it — remove them")
    if "your" in key.lower() or "paste" in key.lower():
        print("⚠️  WARNING: BINANCE_API_KEY still has placeholder text")

if secret:
    if " " in secret:
        print("⚠️  WARNING: BINANCE_API_SECRET has spaces in it — remove them")
    if secret.startswith('"') or secret.startswith("'"):
        print("⚠️  WARNING: BINANCE_API_SECRET has quotes around it — remove them")
    if "your" in secret.lower() or "paste" in secret.lower():
        print("⚠️  WARNING: BINANCE_API_SECRET still has placeholder text")

# Test Binance connection
print()
print("Testing Binance testnet connection...")
try:
    import requests
    r = requests.get("https://testnet.binance.vision/api/v3/ping", timeout=5)
    if r.status_code == 200:
        print("✅ Binance testnet reachable")
    else:
        print(f"❌ Binance testnet returned {r.status_code}")
except Exception as e:
    print(f"❌ Cannot reach Binance testnet: {e}")

# Test account access if keys exist
if key and secret:
    print()
    print("Testing API key authentication...")
    try:
        import hmac, hashlib, time
        from urllib.parse import urlencode
        params = {"timestamp": int(time.time() * 1000)}
        sig = hmac.new(secret.encode(), urlencode(params).encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        r = requests.get(
            "https://testnet.binance.vision/api/v3/account",
            params=params,
            headers={"X-MBX-APIKEY": key},
            timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            balances = [b for b in data.get("balances", []) if float(b["free"]) > 0]
            print("✅ API authentication successful!")
            print(f"   Account balances:")
            for b in balances[:8]:
                print(f"   {b['asset']:10s}: {float(b['free']):.4f}")
        else:
            print(f"❌ API auth failed ({r.status_code}): {r.json()}")
    except Exception as e:
        print(f"❌ API test error: {e}")

print()
print("=" * 50)
