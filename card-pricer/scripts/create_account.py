"""
scripts/create_account.py
-------------------------
Interactive admin helper for creating a new account + owner user.

Usage:
    cd card-pricer
    python -m scripts.create_account

Prompts for:
  - Account display name (e.g. "Robyn's Nest")
  - Owner email + password + display name (this person becomes role='owner')
  - Sandpiper credentials (username, password, account_id, booth)

Sandpiper password is encrypted with SANDPIPER_ENCRYPTION_KEY before storage.
User password is bcrypt-hashed.

Idempotency: if an account with the same name already exists, prompts to abort
or proceed (a duplicate row is created if you proceed — accounts are not
unique-by-name in the schema). Email IS unique — duplicate emails are rejected.

Why a script and not a UI:
  Initial-bootstrap chicken-and-egg — there's no logged-in owner yet to drive
  a /settings flow. Once the first account exists, future accounts can be
  created here too, but in practice the first owner invites teammates from the
  Settings page rather than running this script again.
"""

import getpass
import os
import sys
from pathlib import Path

# Allow running from repo root: `python -m scripts.create_account`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app import database, crypto, auth


def prompt(label: str, *, default: str = "", required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{label}{suffix}: ").strip()
        if not val and default:
            return default
        if val or not required:
            return val
        print("  (required)")


def prompt_password(label: str) -> str:
    while True:
        pw = getpass.getpass(f"{label}: ")
        if not pw:
            print("  (required)")
            continue
        confirm = getpass.getpass(f"{label} (again): ")
        if pw != confirm:
            print("  Passwords don't match — try again.")
            continue
        return pw


def main():
    # Sanity-check env keys before doing any work.
    if not os.getenv("SESSION_SECRET"):
        print("ERROR: SESSION_SECRET is not set in env.", file=sys.stderr)
        print("Generate one with:", file=sys.stderr)
        print('  python -c "import secrets; print(secrets.token_urlsafe(32))"', file=sys.stderr)
        sys.exit(1)

    if not os.getenv("SANDPIPER_ENCRYPTION_KEY"):
        print("ERROR: SANDPIPER_ENCRYPTION_KEY is not set in env.", file=sys.stderr)
        print("Generate one with:", file=sys.stderr)
        print('  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"', file=sys.stderr)
        sys.exit(1)

    print("Initializing database (creates tables if missing)…")
    database.init_db()

    print()
    print("─── Account ──────────────────────────────────────────")
    account_name = prompt("Account display name (e.g. 'Robyn's Nest')")

    existing = [a for a in database.list_accounts() if a["name"].lower() == account_name.lower()]
    if existing:
        print(f"  ⚠  An account named {account_name!r} already exists (id={existing[0]['id']}).")
        if prompt("  Create a duplicate anyway? (y/N)", default="N").lower() != "y":
            print("Aborted.")
            sys.exit(0)

    print()
    print("─── Sandpiper credentials ─────────────────────────────")
    sp_username   = prompt("Sandpiper username")
    sp_password   = prompt_password("Sandpiper password")
    sp_account_id = prompt("Sandpiper account_id")
    sp_booth      = prompt("Sandpiper booth")

    print()
    print("─── Owner user ────────────────────────────────────────")
    owner_email = prompt("Owner email").lower()
    if database.get_user_by_email(owner_email):
        print(f"  ✗  A user with email {owner_email!r} already exists.", file=sys.stderr)
        print("     Pick a different email or delete the existing user first.", file=sys.stderr)
        sys.exit(1)
    owner_display = prompt("Owner display name", default=owner_email.split("@")[0])
    owner_password = prompt_password("Owner password (used to log in)")

    print()
    print("─── Confirm ───────────────────────────────────────────")
    print(f"  Account:       {account_name}")
    print(f"  Sandpiper:     {sp_username} / booth={sp_booth} / account_id={sp_account_id}")
    print(f"  Owner:         {owner_display} <{owner_email}>")
    if prompt("  Create? (Y/n)", default="Y").lower() != "y":
        print("Aborted.")
        sys.exit(0)

    encrypted_pw = crypto.encrypt(sp_password)
    account_id = database.create_account(
        name=account_name,
        sandpiper_username=sp_username,
        sandpiper_password=encrypted_pw,
        sandpiper_account_id=sp_account_id,
        sandpiper_booth=sp_booth,
    )

    user_id = database.create_user(
        account_id=account_id,
        email=owner_email,
        password_hash=auth.hash_password(owner_password),
        display_name=owner_display,
        role="owner",
    )

    print()
    print(f"✓ Account #{account_id} created — owner user #{user_id} ({owner_email})")
    print("  Log in at /login with the email + password you just set.")


if __name__ == "__main__":
    main()
