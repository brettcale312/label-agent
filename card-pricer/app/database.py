"""
database.py
-----------
SQLite database layer for card-pricer.
Uses Python's built-in sqlite3 — no ORM needed at this scale.

Schema:
  accounts — tenants. Own Sandpiper credentials and a data pool.
  users    — individuals belonging to one account.
  invites  — pending team invitations.
  batches  — groups of cards photographed together (scoped by account_id).
  cards    — individual items in a batch (status: pending → approved → uploaded → printed).
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "card_pricer.db"


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row   # rows behave like dicts
    conn.execute("PRAGMA journal_mode=WAL")   # safer for concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Init (create tables if they don't exist)
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                name                     TEXT NOT NULL,
                sandpiper_username       TEXT,
                sandpiper_password       TEXT,
                sandpiper_account_id     TEXT,
                sandpiper_booth          TEXT,
                created_at               TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id      INTEGER NOT NULL REFERENCES accounts(id),
                email           TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                display_name    TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'member',
                created_at      TEXT NOT NULL,
                last_login_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS invites (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id   INTEGER NOT NULL REFERENCES accounts(id),
                email        TEXT NOT NULL,
                token        TEXT NOT NULL UNIQUE,
                invited_by   INTEGER NOT NULL REFERENCES users(id),
                expires_at   TEXT NOT NULL,
                accepted_at  TEXT,
                created_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_account ON users(account_id);
            CREATE INDEX IF NOT EXISTS idx_invites_token ON invites(token);

            CREATE TABLE IF NOT EXISTS batches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                notes       TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'open',
                created_at  TEXT NOT NULL,
                closed_at   TEXT
            );

            CREATE TABLE IF NOT EXISTS cards (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id             INTEGER NOT NULL REFERENCES batches(id),
                sequence_num         INTEGER NOT NULL,
                status               TEXT NOT NULL DEFAULT 'pending',

                -- Card identity
                card_name            TEXT,
                set_name             TEXT,
                card_number          TEXT,
                display_title        TEXT,
                rarity               TEXT,
                condition            TEXT,
                publisher_brand      TEXT,
                year                 TEXT,

                -- Label content (2 bullets on label; 3rd stored for flexibility)
                bullet_1             TEXT,
                bullet_2             TEXT,
                bullet_3             TEXT,

                -- Pricing
                price_source         TEXT,
                base_price           REAL,
                final_price          REAL,
                ai_price_low         REAL,
                ai_price_high        REAL,
                ai_price_confidence  TEXT,

                -- Sandpiper (filled after batch upload)
                inventory_number     TEXT,
                barcode              TEXT,
                sandpiper_error      TEXT,

                -- Meta
                image_path           TEXT,
                search_query         TEXT,
                ai_notes             TEXT,

                created_at           TEXT NOT NULL,
                uploaded_at          TEXT,
                printed_at           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cards_batch
                ON cards(batch_id, sequence_num);
            CREATE INDEX IF NOT EXISTS idx_cards_status
                ON cards(status);
        """)
        # Live migration: add columns to existing databases. Each ALTER is
        # wrapped individually so later columns still apply when earlier ones
        # already exist. Ignore "duplicate column" errors.
        _live_migrations = [
            "ALTER TABLE batches ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
            # Generalist-mode (Phase 1) columns — unused when ENABLE_GENERALIST_MODE=false
            "ALTER TABLE batches ADD COLUMN category TEXT",
            "ALTER TABLE cards   ADD COLUMN category TEXT",
            "ALTER TABLE cards   ADD COLUMN era TEXT",
            "ALTER TABLE cards   ADD COLUMN maker TEXT",
            "ALTER TABLE cards   ADD COLUMN material TEXT",
            "ALTER TABLE cards   ADD COLUMN dimensions TEXT",
            "ALTER TABLE cards   ADD COLUMN makers_mark_image_path TEXT",
            "ALTER TABLE cards   ADD COLUMN price_user_confirmed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE cards   ADD COLUMN upc TEXT",
            # Multi-tenancy: scope batches to an account and track who created them.
            # Existing rows get NULL — backfilled by seed_default_account() on first boot.
            "ALTER TABLE batches ADD COLUMN account_id INTEGER REFERENCES accounts(id)",
            "ALTER TABLE batches ADD COLUMN created_by_user_id INTEGER REFERENCES users(id)",
        ]
        for stmt in _live_migrations:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # Column already exists


# ─────────────────────────────────────────────────────────────────────────────
# Batch operations
# ─────────────────────────────────────────────────────────────────────────────

def create_batch(
    name: str,
    notes: str = "",
    category: Optional[str] = None,
    account_id: Optional[int] = None,
    created_by_user_id: Optional[int] = None,
) -> int:
    """Create a new open batch. Returns new batch id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO batches (name, notes, status, created_at, category, account_id, created_by_user_id) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?)",
            (name, notes or "", _now(), category, account_id, created_by_user_id),
        )
        return cur.lastrowid


def close_batch(batch_id: int):
    """Mark a batch as closed (no more cards can be added)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status='closed', closed_at=? WHERE id=?",
            (_now(), batch_id),
        )


def get_batch(batch_id: int, account_id: Optional[int] = None) -> Optional[dict]:
    """Fetch a batch. If account_id is provided, returns None when the batch belongs
    to a different account — making cross-tenant ID guessing impossible by construction."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT * FROM batches WHERE id=? AND account_id=?",
                (batch_id, account_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None


def list_batches(
    include_archived: bool = False,
    account_id: Optional[int] = None,
) -> list[dict]:
    """All batches for an account (or all batches when account_id is None — admin only),
    newest first, with card counts. Archived excluded by default."""
    clauses = []
    params: list = []
    if not include_archived:
        clauses.append("b.status != 'archived'")
    if account_id is not None:
        clauses.append("b.account_id = ?")
        params.append(account_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT b.*,
                   COUNT(c.id)                                      AS total_cards,
                   SUM(CASE WHEN c.status='pending'  THEN 1 END)   AS pending_count,
                   SUM(CASE WHEN c.status='approved' THEN 1 END)   AS approved_count,
                   SUM(CASE WHEN c.status='uploaded' THEN 1 END)   AS uploaded_count,
                   SUM(CASE WHEN c.status='printed'  THEN 1 END)   AS printed_count
            FROM batches b
            LEFT JOIN cards c ON c.batch_id = b.id
            {where}
            GROUP BY b.id
            ORDER BY b.id DESC
        """, params).fetchall()
        return [dict(r) for r in rows]


def archive_batch(batch_id: int, account_id: Optional[int] = None):
    """
    Archive a batch and mark all its cards as 'archived'.
    Archived cards are hidden from all default grid views but stay in the DB.
    """
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "UPDATE batches SET status='archived', closed_at=? WHERE id=? AND account_id=?",
                (_now(), batch_id, account_id),
            )
            conn.execute(
                "UPDATE cards SET status='archived' WHERE batch_id=? AND batch_id IN "
                "(SELECT id FROM batches WHERE account_id=?)",
                (batch_id, account_id),
            )
        else:
            conn.execute(
                "UPDATE batches SET status='archived', closed_at=? WHERE id=?",
                (_now(), batch_id),
            )
            conn.execute(
                "UPDATE cards SET status='archived' WHERE batch_id=?",
                (batch_id,),
            )


def unarchive_batch(batch_id: int, account_id: Optional[int] = None):
    """
    Restore an archived batch to 'closed' and set its cards back to 'printed'.
    """
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "UPDATE batches SET status='closed', closed_at=NULL WHERE id=? AND account_id=?",
                (batch_id, account_id),
            )
            conn.execute(
                "UPDATE cards SET status='printed' WHERE batch_id=? AND status='archived' "
                "AND batch_id IN (SELECT id FROM batches WHERE account_id=?)",
                (batch_id, account_id),
            )
        else:
            conn.execute(
                "UPDATE batches SET status='closed', closed_at=NULL WHERE id=?",
                (batch_id,),
            )
            conn.execute(
                "UPDATE cards SET status='printed' WHERE batch_id=? AND status='archived'",
                (batch_id,),
            )


def delete_batch(batch_id: int, account_id: Optional[int] = None):
    """Hard-delete a batch and all its cards."""
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "DELETE FROM cards WHERE batch_id=? AND batch_id IN "
                "(SELECT id FROM batches WHERE account_id=?)",
                (batch_id, account_id),
            )
            conn.execute(
                "DELETE FROM batches WHERE id=? AND account_id=?",
                (batch_id, account_id),
            )
        else:
            conn.execute("DELETE FROM cards WHERE batch_id=?", (batch_id,))
            conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))


def prune_empty_batches():
    """Remove batches that have no cards (e.g. accidentally created ones)."""
    with get_conn() as conn:
        conn.execute("""
            DELETE FROM batches
            WHERE id NOT IN (SELECT DISTINCT batch_id FROM cards)
              AND status != 'archived'
        """)


def get_open_batch(account_id: Optional[int] = None) -> Optional[dict]:
    """Return the currently open batch for an account, if any."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT * FROM batches WHERE status='open' AND account_id=? "
                "ORDER BY id DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM batches WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Card operations
# ─────────────────────────────────────────────────────────────────────────────

def next_sequence_num(batch_id: int) -> int:
    """Return the next sequence number for a card in this batch."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence_num), 0) + 1 FROM cards WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        return row[0]


def insert_card(batch_id: int, data: dict) -> int:
    """Insert a new card. Returns the new card id."""
    seq = next_sequence_num(batch_id)
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO cards (
                batch_id, sequence_num, status,
                card_name, set_name, card_number, display_title,
                rarity, condition, publisher_brand, year,
                bullet_1, bullet_2, bullet_3,
                price_source, base_price, final_price,
                ai_price_low, ai_price_high, ai_price_confidence,
                inventory_number, barcode,
                image_path, search_query, ai_notes,
                category, era, maker, material, dimensions,
                makers_mark_image_path, price_user_confirmed,
                upc, created_at
            ) VALUES (
                :batch_id, :sequence_num, 'pending',
                :card_name, :set_name, :card_number, :display_title,
                :rarity, :condition, :publisher_brand, :year,
                :bullet_1, :bullet_2, :bullet_3,
                :price_source, :base_price, :final_price,
                :ai_price_low, :ai_price_high, :ai_price_confidence,
                :inventory_number, :barcode,
                :image_path, :search_query, :ai_notes,
                :category, :era, :maker, :material, :dimensions,
                :makers_mark_image_path, :price_user_confirmed,
                :upc, :created_at
            )
        """, {
            "batch_id": batch_id,
            "sequence_num": seq,
            "card_name": data.get("card_name") or data.get("title", ""),
            "set_name": data.get("set_name", ""),
            "card_number": data.get("card_number", ""),
            "display_title": data.get("display_title") or data.get("title", ""),
            "rarity": data.get("rarity", ""),
            "condition": data.get("condition", ""),
            "publisher_brand": data.get("publisher_brand", ""),
            "year": data.get("year", ""),
            "bullet_1": data.get("bullet_1", ""),
            "bullet_2": data.get("bullet_2", ""),
            "bullet_3": data.get("bullet_3", ""),
            "price_source": data.get("price_source", ""),
            "base_price": data.get("base_price"),
            "final_price": data.get("price") or data.get("final_price"),
            "ai_price_low": data.get("ai_price_low"),
            "ai_price_high": data.get("ai_price_high"),
            "ai_price_confidence": data.get("ai_price_confidence", ""),
            "inventory_number": data.get("inventory_number", ""),
            "barcode": data.get("barcode", ""),
            "image_path": data.get("image_path", ""),
            "search_query": data.get("search_query", ""),
            "ai_notes": data.get("ai_notes", ""),
            "category": data.get("category"),
            "era": data.get("era"),
            "maker": data.get("maker"),
            "material": data.get("material"),
            "dimensions": data.get("dimensions"),
            "makers_mark_image_path": data.get("makers_mark_image_path"),
            "price_user_confirmed": 1 if data.get("price_user_confirmed") else 0,
            "upc": data.get("upc"),
            "created_at": _now(),
        })
        return cur.lastrowid


def get_card(card_id: int, account_id: Optional[int] = None) -> Optional[dict]:
    """Fetch a card. If account_id is provided, returns None when the card's batch
    belongs to a different account — cross-tenant access blocked at the query level."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT c.* FROM cards c "
                "JOIN batches b ON c.batch_id = b.id "
                "WHERE c.id=? AND b.account_id=?",
                (card_id, account_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        return dict(row) if row else None


def list_cards(
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    exclude_archived: bool = False,
    account_id: Optional[int] = None,
) -> list[dict]:
    """
    List cards, always in sequence order. When account_id is provided, results are
    scoped to that account via a JOIN on batches.
    - exclude_archived=True  → never show archived, regardless of other filters
    - status='archived'      → show only archived cards
    - no status, no exclude  → hide archived by default (global view)
    - batch_id only          → all cards for that batch including archived
    """
    sql = "SELECT c.* FROM cards c"
    if account_id is not None:
        sql += " JOIN batches b ON c.batch_id = b.id"
    sql += " WHERE 1=1"
    params: list = []
    if account_id is not None:
        sql += " AND b.account_id = ?"
        params.append(account_id)
    if batch_id is not None:
        sql += " AND c.batch_id=?"
        params.append(batch_id)
    if status:
        sql += " AND c.status=?"
        params.append(status)
    elif exclude_archived or batch_id is None:
        # Hide archived: explicitly requested, or default global view
        sql += " AND c.status != 'archived'"
    sql += " ORDER BY c.batch_id, c.sequence_num"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def update_card(card_id: int, fields: dict, account_id: Optional[int] = None):
    """
    Update arbitrary fields on a card. Only touches columns that are provided.
    Safe — ignores unknown keys. When account_id is provided, the UPDATE is no-op
    if the card belongs to a different account.
    """
    allowed = {
        "display_title", "card_name", "set_name", "card_number", "rarity",
        "condition", "publisher_brand", "year",
        "bullet_1", "bullet_2", "bullet_3",
        "price_source", "base_price", "final_price",
        "inventory_number", "barcode", "sandpiper_error",
        "status", "ai_notes", "uploaded_at", "printed_at",
        # Generalist fields
        "category", "era", "maker", "material", "dimensions",
        "makers_mark_image_path", "price_user_confirmed", "upc",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [card_id]
    with get_conn() as conn:
        if account_id is not None:
            values.append(account_id)
            conn.execute(
                f"UPDATE cards SET {set_clause} WHERE id=? AND batch_id IN "
                f"(SELECT id FROM batches WHERE account_id=?)",
                values,
            )
        else:
            conn.execute(f"UPDATE cards SET {set_clause} WHERE id=?", values)


def approve_cards(card_ids: list[int], account_id: Optional[int] = None):
    """Mark a list of cards as approved."""
    if not card_ids:
        return
    with get_conn() as conn:
        if account_id is not None:
            placeholders = ",".join("?" * len(card_ids))
            params = list(card_ids) + [account_id]
            conn.execute(
                f"UPDATE cards SET status='approved' "
                f"WHERE id IN ({placeholders}) AND status='pending' "
                f"AND batch_id IN (SELECT id FROM batches WHERE account_id=?)",
                params,
            )
        else:
            conn.executemany(
                "UPDATE cards SET status='approved' WHERE id=? AND status='pending'",
                [(cid,) for cid in card_ids],
            )


def get_approved_cards(batch_id: int, account_id: Optional[int] = None) -> list[dict]:
    """Get approved cards for a batch, in sequence order. Used for Sandpiper upload."""
    return list_cards(batch_id=batch_id, status="approved", account_id=account_id)


def get_uploaded_cards(
    batch_id: Optional[int] = None,
    account_id: Optional[int] = None,
) -> list[dict]:
    """Get uploaded cards (have barcodes). Used for label printing."""
    return list_cards(batch_id=batch_id, status="uploaded", account_id=account_id)


def mark_uploaded(card_id: int, inventory_number: str, barcode: str):
    """Mark a card as uploaded with its Sandpiper inventory number and barcode."""
    update_card(card_id, {
        "status": "uploaded",
        "inventory_number": inventory_number,
        "barcode": barcode,
        "uploaded_at": _now(),
        "sandpiper_error": None,
    })


def mark_sandpiper_error(card_id: int, error: str):
    """Mark a card's Sandpiper upload as failed (leaves status as approved for retry)."""
    update_card(card_id, {"sandpiper_error": error})


def mark_printed(card_ids: list[int]):
    with get_conn() as conn:
        conn.executemany(
            "UPDATE cards SET status='printed', printed_at=? WHERE id=?",
            [(_now(), cid) for cid in card_ids],
        )


def duplicate_card(card_id: int, account_id: Optional[int] = None) -> Optional[int]:
    """
    Copy a card into the same batch with a fresh sequence number, inventory number,
    and pending status. Barcode/upload fields are cleared. Returns new card id.
    Returns None if the card doesn't exist or belongs to a different account.
    """
    card = get_card(card_id, account_id=account_id)
    if not card:
        return None
    inv = get_next_inv_number(account_id=account_id)
    seq = next_sequence_num(card["batch_id"])
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO cards (
                batch_id, sequence_num, status,
                card_name, set_name, card_number, display_title,
                rarity, condition, publisher_brand, year,
                bullet_1, bullet_2, bullet_3,
                price_source, base_price, final_price,
                ai_price_low, ai_price_high, ai_price_confidence,
                inventory_number, barcode,
                image_path, search_query, ai_notes,
                category, era, maker, material, dimensions,
                makers_mark_image_path, price_user_confirmed,
                created_at
            ) VALUES (
                ?,?,  'pending',
                ?,?,?,?,  ?,?,?,?,
                ?,?,?,
                ?,?,?,  ?,?,?,
                ?,?,
                ?,?,?,
                ?,?,?,?,?,
                ?,?,
                ?
            )
        """, (
            card["batch_id"], seq,
            card["card_name"], card["set_name"], card["card_number"], card["display_title"],
            card["rarity"], card["condition"], card["publisher_brand"], card["year"],
            card["bullet_1"], card["bullet_2"], card["bullet_3"],
            card["price_source"], card["base_price"], card["final_price"],
            card["ai_price_low"], card["ai_price_high"], card["ai_price_confidence"],
            inv, "",
            card["image_path"], card["search_query"], card["ai_notes"],
            card.get("category"), card.get("era"), card.get("maker"),
            card.get("material"), card.get("dimensions"),
            card.get("makers_mark_image_path"), card.get("price_user_confirmed") or 0,
            _now(),
        ))
        return cur.lastrowid


def delete_cards(card_ids: list[int], account_id: Optional[int] = None):
    """Hard-delete cards by id. When account_id is provided, only cards belonging to
    that account are deleted; cross-tenant ids in the list are silently ignored."""
    if not card_ids:
        return
    placeholders = ",".join("?" * len(card_ids))
    with get_conn() as conn:
        if account_id is not None:
            params = list(card_ids) + [account_id]
            conn.execute(
                f"DELETE FROM cards WHERE id IN ({placeholders}) "
                f"AND batch_id IN (SELECT id FROM batches WHERE account_id=?)",
                params,
            )
        else:
            conn.execute(f"DELETE FROM cards WHERE id IN ({placeholders})", card_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory number (local, no Sheets dependency)
# ─────────────────────────────────────────────────────────────────────────────

INV_START = 10000

def get_next_inv_number(account_id: Optional[int] = None) -> str:
    """
    Generate the next sequential inventory number for an account (or globally if no
    account is provided — admin/legacy use only). Starts at 10000 and increments by 1.
    """
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT MAX(CAST(c.inventory_number AS INTEGER)) "
                "FROM cards c JOIN batches b ON c.batch_id = b.id "
                "WHERE b.account_id=? AND c.inventory_number GLOB '[0-9]*'",
                (account_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(CAST(inventory_number AS INTEGER)) FROM cards "
                "WHERE inventory_number GLOB '[0-9]*'"
            ).fetchone()
        last = row[0] if row[0] else INV_START - 1
        return str(last + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# Accounts
# ─────────────────────────────────────────────────────────────────────────────

def create_account(
    name: str,
    sandpiper_username: Optional[str] = None,
    sandpiper_password: Optional[str] = None,
    sandpiper_account_id: Optional[str] = None,
    sandpiper_booth: Optional[str] = None,
) -> int:
    """Create a new account. Sandpiper password should already be encrypted."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO accounts (name, sandpiper_username, sandpiper_password, "
            "sandpiper_account_id, sandpiper_booth, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, sandpiper_username, sandpiper_password, sandpiper_account_id,
             sandpiper_booth, _now()),
        )
        return cur.lastrowid


def get_account(account_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return dict(row) if row else None


def list_accounts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def update_account(account_id: int, fields: dict):
    """Update account fields. Sandpiper password should be pre-encrypted by caller."""
    allowed = {
        "name", "sandpiper_username", "sandpiper_password",
        "sandpiper_account_id", "sandpiper_booth",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [account_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE accounts SET {set_clause} WHERE id=?", values)


# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────

def create_user(
    account_id: int,
    email: str,
    password_hash: str,
    display_name: str,
    role: str = "member",
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (account_id, email, password_hash, display_name, role, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, email.lower().strip(), password_hash, display_name, role, _now()),
        )
        return cur.lastrowid


def get_user(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=?",
            (email.lower().strip(),),
        ).fetchone()
        return dict(row) if row else None


def list_users(account_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE account_id=? ORDER BY created_at",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_user_login(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (_now(), user_id))


def update_user(user_id: int, fields: dict, account_id: Optional[int] = None):
    """Update user fields. Caller is responsible for password hashing."""
    allowed = {"password_hash", "display_name", "role"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [user_id]
    with get_conn() as conn:
        if account_id is not None:
            values.append(account_id)
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id=? AND account_id=?",
                values,
            )
        else:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)


# ─────────────────────────────────────────────────────────────────────────────
# Invites
# ─────────────────────────────────────────────────────────────────────────────

def create_invite(
    account_id: int,
    email: str,
    token: str,
    invited_by: int,
    expires_at: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO invites (account_id, email, token, invited_by, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, email.lower().strip(), token, invited_by, expires_at, _now()),
        )
        return cur.lastrowid


def get_invite_by_token(token: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM invites WHERE token=?", (token,),
        ).fetchone()
        return dict(row) if row else None


def list_pending_invites(account_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM invites WHERE account_id=? AND accepted_at IS NULL "
            "ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_invite_accepted(invite_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE invites SET accepted_at=? WHERE id=?",
            (_now(), invite_id),
        )


def delete_invite(invite_id: int, account_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM invites WHERE id=? AND account_id=?",
            (invite_id, account_id),
        )
