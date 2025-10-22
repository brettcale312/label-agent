# scripts/reset_agent.py
import argparse, os, sqlite3, json

DB_PATH = os.getenv("DB_PATH", "database.db")      # adjust if your app uses a different path
STATE_FILE = os.path.join("logs", "agent_state.json")

NUKE_SQL = """
PRAGMA foreign_keys = OFF;
DELETE FROM item;
DELETE FROM learned_pattern;
DELETE FROM pricing_cache;
DELETE FROM user_preference;
DELETE FROM pricing_session;
DELETE FROM sqlite_sequence;
PRAGMA foreign_keys = ON;
VACUUM;
"""

KEEP_PREFS_SQL = """
PRAGMA foreign_keys = OFF;
DELETE FROM item;
DELETE FROM learned_pattern;
DELETE FROM pricing_cache;
DELETE FROM pricing_session;
DELETE FROM sqlite_sequence;
PRAGMA foreign_keys = ON;
VACUUM;
"""

def main(mode: str, reset_messages: bool):
    if not os.path.exists(DB_PATH):
        print(f"[warn] DB file not found at {DB_PATH}. Nothing to reset.")
    else:
        sql = NUKE_SQL if mode == "nuke" else KEEP_PREFS_SQL
        with sqlite3.connect(DB_PATH) as con:
            con.executescript(sql)
        print(f"[ok] Database reset completed ({mode}).")

    if reset_messages:
        try:
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
                print("[ok] Removed logs/agent_state.json (conversation memory).")
            else:
                print("[ok] No agent_state.json found.")
        except Exception as e:
            print(f"[warn] Could not remove agent_state.json: {e}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["nuke", "keep-prefs"], default="keep-prefs",
                   help="nuke: wipe everything; keep-prefs: keep user_preference rows")
    p.add_argument("--reset-messages", action="store_true",
                   help="Also delete logs/agent_state.json (conversation memory)")
    args = p.parse_args()
    main(args.mode, args.reset_messages)
