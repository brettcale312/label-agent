"""
database.py
-----------
SQLite database layer for card-pricer.
Uses Python's built-in sqlite3 — no ORM needed at this scale.

Schema:
  batches  — groups of cards photographed together
  cards    — individual cards with status lifecycle:
             pending → approved → uploaded → printed
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
        # Live migration: add notes column to existing databases
        try:
            conn.execute("ALTER TABLE batches ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass  # Column already exists


# ─────────────────────────────────────────────────────────────────────────────
# Batch operations
# ─────────────────────────────────────────────────────────────────────────────

def create_batch(name: str, notes: str = "") -> int:
    """Create a new open batch. Returns new batch id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO batches (name, notes, status, created_at) VALUES (?, ?, 'open', ?)",
            (name, notes or "", _now()),
        )
        return cur.lastrowid


def close_batch(batch_id: int):
    """Mark a batch as closed (no more cards can be added)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status='closed', closed_at=? WHERE id=?",
            (_now(), batch_id),
        )


def get_batch(batch_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None


def list_batches(include_archived: bool = False) -> list[dict]:
    """All batches, newest first, with card counts. Archived excluded by default."""
    where = "" if include_archived else "WHERE b.status != 'archived'"
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
        """).fetchall()
        return [dict(r) for r in rows]


def archive_batch(batch_id: int):
    """
    Archive a batch and mark all its cards as 'archived'.
    Archived cards are hidden from all default grid views but stay in the DB.
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status='archived', closed_at=? WHERE id=?",
            (_now(), batch_id),
        )
        conn.execute(
            "UPDATE cards SET status='archived' WHERE batch_id=?",
            (batch_id,),
        )


def unarchive_batch(batch_id: int):
    """
    Restore an archived batch to 'closed' and set its cards back to 'printed'
    (the last real status before archiving — they already have barcodes).
    """
    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status='closed', closed_at=NULL WHERE id=?",
            (batch_id,),
        )
        conn.execute(
            "UPDATE cards SET status='printed' WHERE batch_id=? AND status='archived'",
            (batch_id,),
        )


def delete_batch(batch_id: int):
    """Hard-delete a batch and all its cards."""
    with get_conn() as conn:
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


def get_open_batch() -> Optional[dict]:
    """Return the currently open batch, if any."""
    with get_conn() as conn:
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
                created_at
            ) VALUES (
                :batch_id, :sequence_num, 'pending',
                :card_name, :set_name, :card_number, :display_title,
                :rarity, :condition, :publisher_brand, :year,
                :bullet_1, :bullet_2, :bullet_3,
                :price_source, :base_price, :final_price,
                :ai_price_low, :ai_price_high, :ai_price_confidence,
                :inventory_number, :barcode,
                :image_path, :search_query, :ai_notes,
                :created_at
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
            "created_at": _now(),
        })
        return cur.lastrowid


def get_card(card_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        return dict(row) if row else None


def list_cards(
    batch_id: Optional[int] = None,
    status: Optional[str] = None,
    exclude_archived: bool = False,
) -> list[dict]:
    """
    List cards, always in sequence order.
    - exclude_archived=True  → never show archived, regardless of other filters
    - status='archived'      → show only archived cards
    - no status, no exclude  → hide archived by default (global view)
    - batch_id only          → all cards for that batch including archived
    """
    sql = "SELECT * FROM cards WHERE 1=1"
    params = []
    if batch_id is not None:
        sql += " AND batch_id=?"
        params.append(batch_id)
    if status:
        sql += " AND status=?"
        params.append(status)
    elif exclude_archived or batch_id is None:
        # Hide archived: explicitly requested, or default global view
        sql += " AND status != 'archived'"
    sql += " ORDER BY batch_id, sequence_num"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def update_card(card_id: int, fields: dict):
    """
    Update arbitrary fields on a card. Only touches columns that are provided.
    Safe — ignores unknown keys.
    """
    allowed = {
        "display_title", "card_name", "set_name", "card_number", "rarity",
        "condition", "publisher_brand", "year",
        "bullet_1", "bullet_2", "bullet_3",
        "price_source", "base_price", "final_price",
        "inventory_number", "barcode", "sandpiper_error",
        "status", "ai_notes", "uploaded_at", "printed_at",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [card_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE cards SET {set_clause} WHERE id=?", values)


def approve_cards(card_ids: list[int]):
    """Mark a list of cards as approved."""
    with get_conn() as conn:
        conn.executemany(
            "UPDATE cards SET status='approved' WHERE id=? AND status='pending'",
            [(cid,) for cid in card_ids],
        )


def get_approved_cards(batch_id: int) -> list[dict]:
    """Get approved cards for a batch, in sequence order. Used for Sandpiper upload."""
    return list_cards(batch_id=batch_id, status="approved")


def get_uploaded_cards(batch_id: Optional[int] = None) -> list[dict]:
    """Get uploaded cards (have barcodes). Used for label printing."""
    return list_cards(batch_id=batch_id, status="uploaded")


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


def duplicate_card(card_id: int) -> Optional[int]:
    """
    Copy a card into the same batch with a fresh sequence number, inventory number,
    and pending status. Barcode/upload fields are cleared. Returns new card id.
    """
    card = get_card(card_id)
    if not card:
        return None
    inv = get_next_inv_number()
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
                created_at
            ) VALUES (
                ?,?,  'pending',
                ?,?,?,?,  ?,?,?,?,
                ?,?,?,
                ?,?,?,  ?,?,?,
                ?,?,
                ?,?,?,
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
            _now(),
        ))
        return cur.lastrowid


def delete_cards(card_ids: list[int]):
    """Hard-delete cards by id. No status restriction — any card can be deleted."""
    if not card_ids:
        return
    placeholders = ",".join("?" * len(card_ids))
    with get_conn() as conn:
        conn.execute(f"DELETE FROM cards WHERE id IN ({placeholders})", card_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory number (local, no Sheets dependency)
# ─────────────────────────────────────────────────────────────────────────────

INV_START = 10000

def get_next_inv_number() -> str:
    """
    Generate the next sequential inventory number.
    Starts at 10000 and increments by 1 per card.
    Reads the current max from the DB so it's always correct even after restarts.
    """
    with get_conn() as conn:
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
