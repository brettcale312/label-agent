"""
database.py
-----------
PostgreSQL database layer for card-pricer (psycopg v3).

Requires DATABASE_URL env var — auto-injected by Railway when the Postgres
plugin is attached. For local dev, copy DATABASE_URL from Railway Variables
into your .env file.

Schema:
  accounts — tenants. Own Sandpiper credentials and a data pool.
  users    — individuals belonging to one account.
  invites  — pending team invitations.
  batches  — groups of cards photographed together (scoped by account_id).
  cards    — individual items in a batch (status: pending → approved → uploaded → printed).
"""

import os
from datetime import datetime
from typing import Optional

import psycopg
from psycopg.rows import dict_row


# ─────────────────────────────────────────────────────────────────────────────
# Connection
# ─────────────────────────────────────────────────────────────────────────────

def get_conn() -> psycopg.Connection:
    """Return an open psycopg connection. Rows come back as plain dicts via dict_row.
    Use as a context manager — commits on clean exit, rolls back on exception."""
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# Init (create tables if they don't exist + live migrations)
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        # ── Core tables ──────────────────────────────────────────────────────
        conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id                       SERIAL PRIMARY KEY,
                name                     TEXT NOT NULL,
                sandpiper_username       TEXT,
                sandpiper_password       TEXT,
                sandpiper_account_id     TEXT,
                sandpiper_booth          TEXT,
                created_at               TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              SERIAL PRIMARY KEY,
                account_id      INTEGER NOT NULL REFERENCES accounts(id),
                email           TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                display_name    TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'member',
                created_at      TEXT NOT NULL,
                last_login_at   TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS invites (
                id           SERIAL PRIMARY KEY,
                account_id   INTEGER NOT NULL REFERENCES accounts(id),
                email        TEXT NOT NULL,
                token        TEXT NOT NULL UNIQUE,
                invited_by   INTEGER NOT NULL REFERENCES users(id),
                expires_at   TEXT NOT NULL,
                accepted_at  TEXT,
                created_at   TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS batches (
                id                   SERIAL PRIMARY KEY,
                name                 TEXT NOT NULL,
                notes                TEXT NOT NULL DEFAULT '',
                status               TEXT NOT NULL DEFAULT 'open',
                created_at           TEXT NOT NULL,
                closed_at            TEXT,
                category             TEXT,
                account_id           INTEGER REFERENCES accounts(id),
                created_by_user_id   INTEGER REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id                   SERIAL PRIMARY KEY,
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
                base_price           DOUBLE PRECISION,
                final_price          DOUBLE PRECISION,
                ai_price_low         DOUBLE PRECISION,
                ai_price_high        DOUBLE PRECISION,
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
                printed_at           TEXT,

                -- Generalist-mode fields
                category             TEXT,
                era                  TEXT,
                maker                TEXT,
                material             TEXT,
                dimensions           TEXT,
                makers_mark_image_path TEXT,
                price_user_confirmed INTEGER NOT NULL DEFAULT 0,
                upc                  TEXT
            )
        """)

        # ── Indexes ──────────────────────────────────────────────────────────
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_account  ON users(account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_invites_token  ON invites(token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_batch    ON cards(batch_id, sequence_num)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_status   ON cards(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_batches_account ON batches(account_id)")

        # ── Live migrations (ADD COLUMN IF NOT EXISTS — Postgres native) ─────
        # These are no-ops on a fresh DB; they apply safely to existing ones.
        _migrations = [
            "ALTER TABLE batches ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE batches ADD COLUMN IF NOT EXISTS category TEXT",
            "ALTER TABLE batches ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES accounts(id)",
            "ALTER TABLE batches ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id)",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS category TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS era TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS maker TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS material TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS dimensions TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS makers_mark_image_path TEXT",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS price_user_confirmed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE cards   ADD COLUMN IF NOT EXISTS upc TEXT",
            "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS label_format TEXT NOT NULL DEFAULT 'auto'",
        ]
        for stmt in _migrations:
            conn.execute(stmt)


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
        row = conn.execute(
            "INSERT INTO batches (name, notes, status, created_at, category, account_id, created_by_user_id) "
            "VALUES (%s, %s, 'open', %s, %s, %s, %s) RETURNING id",
            (name, notes or "", _now(), category, account_id, created_by_user_id),
        ).fetchone()
        return row["id"]


def close_batch(batch_id: int):
    """Mark a batch as closed (no more cards can be added)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status='closed', closed_at=%s WHERE id=%s",
            (_now(), batch_id),
        )


def get_batch(batch_id: int, account_id: Optional[int] = None) -> Optional[dict]:
    """Fetch a batch. If account_id is provided, returns None when the batch belongs
    to a different account — making cross-tenant ID guessing impossible by construction."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT * FROM batches WHERE id=%s AND account_id=%s",
                (batch_id, account_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM batches WHERE id=%s", (batch_id,)).fetchone()
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
        clauses.append("b.account_id = %s")
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
    """Archive a batch and mark all its cards as 'archived'."""
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "UPDATE batches SET status='archived', closed_at=%s WHERE id=%s AND account_id=%s",
                (_now(), batch_id, account_id),
            )
            conn.execute(
                "UPDATE cards SET status='archived' WHERE batch_id=%s AND batch_id IN "
                "(SELECT id FROM batches WHERE account_id=%s)",
                (batch_id, account_id),
            )
        else:
            conn.execute(
                "UPDATE batches SET status='archived', closed_at=%s WHERE id=%s",
                (_now(), batch_id),
            )
            conn.execute(
                "UPDATE cards SET status='archived' WHERE batch_id=%s",
                (batch_id,),
            )


def unarchive_batch(batch_id: int, account_id: Optional[int] = None):
    """Restore an archived batch to 'closed' and set its cards back to 'printed'."""
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "UPDATE batches SET status='closed', closed_at=NULL WHERE id=%s AND account_id=%s",
                (batch_id, account_id),
            )
            conn.execute(
                "UPDATE cards SET status='printed' WHERE batch_id=%s AND status='archived' "
                "AND batch_id IN (SELECT id FROM batches WHERE account_id=%s)",
                (batch_id, account_id),
            )
        else:
            conn.execute(
                "UPDATE batches SET status='closed', closed_at=NULL WHERE id=%s",
                (batch_id,),
            )
            conn.execute(
                "UPDATE cards SET status='printed' WHERE batch_id=%s AND status='archived'",
                (batch_id,),
            )


def delete_batch(batch_id: int, account_id: Optional[int] = None):
    """Hard-delete a batch and all its cards."""
    with get_conn() as conn:
        if account_id is not None:
            conn.execute(
                "DELETE FROM cards WHERE batch_id=%s AND batch_id IN "
                "(SELECT id FROM batches WHERE account_id=%s)",
                (batch_id, account_id),
            )
            conn.execute(
                "DELETE FROM batches WHERE id=%s AND account_id=%s",
                (batch_id, account_id),
            )
        else:
            conn.execute("DELETE FROM cards WHERE batch_id=%s", (batch_id,))
            conn.execute("DELETE FROM batches WHERE id=%s", (batch_id,))


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
                "SELECT * FROM batches WHERE status='open' AND account_id=%s "
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
            "SELECT COALESCE(MAX(sequence_num), 0) + 1 AS next_seq FROM cards WHERE batch_id=%s",
            (batch_id,),
        ).fetchone()
        return row["next_seq"]


def insert_card(batch_id: int, data: dict) -> int:
    """Insert a new card. Returns the new card id."""
    seq = next_sequence_num(batch_id)
    with get_conn() as conn:
        row = conn.execute("""
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
                %(batch_id)s, %(sequence_num)s, 'pending',
                %(card_name)s, %(set_name)s, %(card_number)s, %(display_title)s,
                %(rarity)s, %(condition)s, %(publisher_brand)s, %(year)s,
                %(bullet_1)s, %(bullet_2)s, %(bullet_3)s,
                %(price_source)s, %(base_price)s, %(final_price)s,
                %(ai_price_low)s, %(ai_price_high)s, %(ai_price_confidence)s,
                %(inventory_number)s, %(barcode)s,
                %(image_path)s, %(search_query)s, %(ai_notes)s,
                %(category)s, %(era)s, %(maker)s, %(material)s, %(dimensions)s,
                %(makers_mark_image_path)s, %(price_user_confirmed)s,
                %(upc)s, %(created_at)s
            ) RETURNING id
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
        }).fetchone()
        return row["id"]


def get_card(card_id: int, account_id: Optional[int] = None) -> Optional[dict]:
    """Fetch a card. If account_id is provided, returns None when the card's batch
    belongs to a different account — cross-tenant access blocked at the query level."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT c.* FROM cards c "
                "JOIN batches b ON c.batch_id = b.id "
                "WHERE c.id=%s AND b.account_id=%s",
                (card_id, account_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM cards WHERE id=%s", (card_id,)).fetchone()
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
    """
    sql = "SELECT c.* FROM cards c"
    if account_id is not None:
        sql += " JOIN batches b ON c.batch_id = b.id"
    sql += " WHERE 1=1"
    params: list = []
    if account_id is not None:
        sql += " AND b.account_id = %s"
        params.append(account_id)
    if batch_id is not None:
        sql += " AND c.batch_id=%s"
        params.append(batch_id)
    if status:
        sql += " AND c.status=%s"
        params.append(status)
    elif exclude_archived or batch_id is None:
        sql += " AND c.status != 'archived'"
    sql += " ORDER BY c.batch_id, c.sequence_num"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def update_card(card_id: int, fields: dict, account_id: Optional[int] = None):
    """Update arbitrary fields on a card. Only touches columns that are provided."""
    allowed = {
        "display_title", "card_name", "set_name", "card_number", "rarity",
        "condition", "publisher_brand", "year",
        "bullet_1", "bullet_2", "bullet_3",
        "price_source", "base_price", "final_price",
        "inventory_number", "barcode", "sandpiper_error",
        "status", "ai_notes", "uploaded_at", "printed_at",
        "category", "era", "maker", "material", "dimensions",
        "makers_mark_image_path", "price_user_confirmed", "upc",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=%s" for k in clean)
    values = list(clean.values()) + [card_id]
    with get_conn() as conn:
        if account_id is not None:
            values.append(account_id)
            conn.execute(
                f"UPDATE cards SET {set_clause} WHERE id=%s AND batch_id IN "
                f"(SELECT id FROM batches WHERE account_id=%s)",
                values,
            )
        else:
            conn.execute(f"UPDATE cards SET {set_clause} WHERE id=%s", values)


def approve_cards(card_ids: list[int], account_id: Optional[int] = None):
    """Mark a list of cards as approved."""
    if not card_ids:
        return
    with get_conn() as conn:
        if account_id is not None:
            placeholders = ",".join(["%s"] * len(card_ids))
            params = list(card_ids) + [account_id]
            conn.execute(
                f"UPDATE cards SET status='approved' "
                f"WHERE id IN ({placeholders}) AND status='pending' "
                f"AND batch_id IN (SELECT id FROM batches WHERE account_id=%s)",
                params,
            )
        else:
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE cards SET status='approved' WHERE id=%s AND status='pending'",
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
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "UPDATE cards SET status='printed', printed_at=%s WHERE id=%s",
            [(_now(), cid) for cid in card_ids],
        )


def duplicate_card(card_id: int, account_id: Optional[int] = None) -> Optional[int]:
    """Copy a card into the same batch with fresh sequence/inventory numbers."""
    card = get_card(card_id, account_id=account_id)
    if not card:
        return None
    inv = get_next_inv_number(account_id=account_id)
    seq = next_sequence_num(card["batch_id"])
    with get_conn() as conn:
        row = conn.execute("""
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
                %s, %s, 'pending',
                %s, %s, %s, %s,  %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,  %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s
            ) RETURNING id
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
        )).fetchone()
        return row["id"]


def delete_cards(card_ids: list[int], account_id: Optional[int] = None):
    """Hard-delete cards by id."""
    if not card_ids:
        return
    placeholders = ",".join(["%s"] * len(card_ids))
    with get_conn() as conn:
        if account_id is not None:
            params = list(card_ids) + [account_id]
            conn.execute(
                f"DELETE FROM cards WHERE id IN ({placeholders}) "
                f"AND batch_id IN (SELECT id FROM batches WHERE account_id=%s)",
                params,
            )
        else:
            conn.execute(f"DELETE FROM cards WHERE id IN ({placeholders})", card_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory number
# ─────────────────────────────────────────────────────────────────────────────

INV_START = 10000

def get_next_inv_number(account_id: Optional[int] = None) -> str:
    """Generate the next sequential inventory number for an account."""
    with get_conn() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT MAX(CAST(c.inventory_number AS INTEGER)) AS max_inv "
                "FROM cards c JOIN batches b ON c.batch_id = b.id "
                "WHERE b.account_id=%s AND c.inventory_number ~ '^[0-9]'",
                (account_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(CAST(inventory_number AS INTEGER)) AS max_inv FROM cards "
                "WHERE inventory_number ~ '^[0-9]'"
            ).fetchone()
        last = row["max_inv"] if row["max_inv"] is not None else INV_START - 1
        return str(last + 1)


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
        row = conn.execute(
            "INSERT INTO accounts (name, sandpiper_username, sandpiper_password, "
            "sandpiper_account_id, sandpiper_booth, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (name, sandpiper_username, sandpiper_password, sandpiper_account_id,
             sandpiper_booth, _now()),
        ).fetchone()
        return row["id"]


def get_account(account_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=%s", (account_id,)).fetchone()
        return dict(row) if row else None


def list_accounts() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def update_account(account_id: int, fields: dict):
    """Update account fields. Sandpiper password should be pre-encrypted by caller."""
    allowed = {
        "name", "sandpiper_username", "sandpiper_password",
        "sandpiper_account_id", "sandpiper_booth", "label_format",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=%s" for k in clean)
    values = list(clean.values()) + [account_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE accounts SET {set_clause} WHERE id=%s", values)


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
        row = conn.execute(
            "INSERT INTO users (account_id, email, password_hash, display_name, role, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (account_id, email.lower().strip(), password_hash, display_name, role, _now()),
        ).fetchone()
        return row["id"]


def get_user(user_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=%s",
            (email.lower().strip(),),
        ).fetchone()
        return dict(row) if row else None


def list_users(account_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE account_id=%s ORDER BY created_at",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_user_login(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET last_login_at=%s WHERE id=%s", (_now(), user_id))


def update_user(user_id: int, fields: dict, account_id: Optional[int] = None):
    """Update user fields. Caller is responsible for password hashing."""
    allowed = {"password_hash", "display_name", "role"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    set_clause = ", ".join(f"{k}=%s" for k in clean)
    values = list(clean.values()) + [user_id]
    with get_conn() as conn:
        if account_id is not None:
            values.append(account_id)
            conn.execute(
                f"UPDATE users SET {set_clause} WHERE id=%s AND account_id=%s",
                values,
            )
        else:
            conn.execute(f"UPDATE users SET {set_clause} WHERE id=%s", values)


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
        row = conn.execute(
            "INSERT INTO invites (account_id, email, token, invited_by, expires_at, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (account_id, email.lower().strip(), token, invited_by, expires_at, _now()),
        ).fetchone()
        return row["id"]


def get_invite_by_token(token: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM invites WHERE token=%s", (token,),
        ).fetchone()
        return dict(row) if row else None


def list_pending_invites(account_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM invites WHERE account_id=%s AND accepted_at IS NULL "
            "ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_invite_accepted(invite_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE invites SET accepted_at=%s WHERE id=%s",
            (_now(), invite_id),
        )


def delete_invite(invite_id: int, account_id: int):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM invites WHERE id=%s AND account_id=%s",
            (invite_id, account_id),
        )
