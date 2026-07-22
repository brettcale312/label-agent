"""
scripts/set_password.py
-----------------------
Admin helper for resetting an existing user's login password.

Usage:
    cd card-pricer
    python -m scripts.set_password                 # prompts for email + password
    python -m scripts.set_password user@example.com
    python -m scripts.set_password user@example.com --password 's3cret' --yes

Looks the user up by email, bcrypt-hashes the new password, and updates the
`password_hash` column via database.update_user — the same field the invite
flow writes. No other fields are touched.

Env: only DATABASE_URL is required (to reach the Railway Postgres). Unlike
create_account.py, this does NOT need SESSION_SECRET or SANDPIPER_ENCRYPTION_KEY,
since bcrypt hashing is self-contained.

Why a script and not a UI:
  There's no self-serve "forgot password" flow yet. This gives an owner/admin
  a safe, non-interactive-capable way to reset a login without minting a whole
  new account or hand-writing SQL against the hash column.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Allow running from repo root: `python -m scripts.set_password`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app import database, auth


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
    parser = argparse.ArgumentParser(description="Reset an existing user's login password.")
    parser.add_argument("email", nargs="?", help="Email of the user to reset (prompted if omitted).")
    parser.add_argument(
        "--password",
        help="New password (INSECURE — visible in shell history/process list). "
        "Omit to be prompted securely.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    email = (args.email or input("User email: ")).lower().strip()
    if not email:
        print("ERROR: email is required.", file=sys.stderr)
        sys.exit(1)

    user = database.get_user_by_email(email)
    if not user:
        print(f"  ✗  No user found with email {email!r}.", file=sys.stderr)
        print("     Check the address, or use scripts/create_account.py to create one.", file=sys.stderr)
        sys.exit(1)

    print()
    print("─── User ──────────────────────────────────────────────")
    print(f"  id:      {user['id']}")
    print(f"  email:   {user['email']}")
    print(f"  name:    {user.get('display_name')}")
    print(f"  role:    {user.get('role')}")
    print(f"  account: {user.get('account_id')}")
    print()

    new_password = args.password or prompt_password("New password")
    if not new_password:
        print("ERROR: password is required.", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        confirm = input(f"Reset password for {email!r}? (y/N): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    database.update_user(user["id"], {"password_hash": auth.hash_password(new_password)})

    print()
    print(f"✓ Password reset for {email} (user #{user['id']}).")
    print("  Log in at /login with the new password.")


if __name__ == "__main__":
    main()
