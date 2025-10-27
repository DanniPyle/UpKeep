#!/usr/bin/env python3
"""
Generate a secure random secret key for Flask applications.
Run this script to generate a new FLASK_SECRET_KEY for your .env file.
"""

import secrets
import string

def generate_secret_key(length=64):
    """Generate a cryptographically secure random secret key."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    secret_key = ''.join(secrets.choice(alphabet) for _ in range(length))
    return secret_key

if __name__ == '__main__':
    key = generate_secret_key()
    print("=" * 70)
    print("🔐 SECURE SECRET KEY GENERATED")
    print("=" * 70)
    print("\nAdd this to your .env file:")
    print(f"\nFLASK_SECRET_KEY={key}")
    print("\n" + "=" * 70)
    print("⚠️  IMPORTANT:")
    print("  - Keep this secret safe")
    print("  - Never commit it to version control")
    print("  - Use a different key for each environment (dev/staging/prod)")
    print("  - Changing this key will invalidate all existing sessions")
    print("=" * 70)
