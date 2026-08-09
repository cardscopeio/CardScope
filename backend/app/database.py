"""
Postgres (Neon) setup for CardScope.io's backend.

Was plain sqlite3 (stdlib) originally, but Render's free web services have an
EPHEMERAL filesystem: any local file (including a SQLite .db file) is wiped
every time the service redeploys, restarts, or spins down from inactivity
(free services sleep after 15 min idle). That's not a rare edge case - it's
normal operation - so every card, account, and offer was silently getting
wiped on a schedule outside our control. Discovered 2026-07-09 when a real
user-submitted card vanished after a routine deploy.

Postgres via Neon (https://neon.tech) fixes this: a real external database
that isn't tied to the backend's filesystem lifecycle. Neon's free tier
never deletes data due to inactivity (unlike Render's own free Postgres,
which auto-deletes after 30 days) - it just suspends compute after 5 minutes
idle and auto-resumes on the next query, transparently.

To keep the rest of the app (main.py) nearly untouched, get_connection()
returns a thin compatibility wrapper that accepts the same sqlite3-style
"?" placeholders and dict-like row access (row["column"]) the code was
already written against - only this file needed to change syntax.

Requires a DATABASE_URL environment variable (a Neon connection string,
e.g. postgresql://user:pass@ep-xxxx.neon.tech/neondb?sslmode=require).
"""
import json
import os
import re
import secrets
import uuid
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. This must be a Neon "
        "(or other Postgres) connection string - see database.py for why "
        "SQLite-on-Render doesn't work. Set it as an env var on Render (and "
        "locally, for testing) before starting the app."
    )


class _CompatCursor:
    """Wraps a psycopg2 RealDictCursor so callers can keep using
    .fetchone()/.fetchall() exactly like the old sqlite3 code did."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class _CompatConnection:
    """Wraps a psycopg2 connection so callers can keep writing
    conn.execute("... WHERE x = ?", (val,)) like the old sqlite3 code did.
    Translates "?" placeholders to psycopg2's "%s" - safe here because none
    of this app's SQL strings contain a literal "?" outside of placeholders."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=()):
        pg_query = query.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(pg_query, params)
        return _CompatCursor(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return _CompatConnection(conn)


def slugify(player_name: str) -> str:
    """Matches the frontend's cardSlug() in cards-data.js so URLs line up."""
    return re.sub(r"[.\s]+", "-", player_name.strip().lower())


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cards (
            slug TEXT PRIMARY KEY,
            player TEXT NOT NULL,
            year TEXT NOT NULL,
            brand TEXT NOT NULL,
            type TEXT NOT NULL,
            era TEXT NOT NULL,
            condition TEXT,
            price_cents INTEGER NOT NULL,
            emoji TEXT DEFAULT '⚾',
            description TEXT,
            manufacturer TEXT,
            autographed INTEGER DEFAULT 0,
            numbered INTEGER DEFAULT 0,
            serial_number TEXT,
            status TEXT DEFAULT 'listed',
            is_user_submitted INTEGER DEFAULT 0,
            date_added TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
            front_image_url TEXT,
            back_image_url TEXT,
            user_id TEXT,
            is_bargain_box INTEGER DEFAULT 0,
            lot_card_count INTEGER
        )
        """
    )
    # Migration for databases created before the Bargain Box (multi-card lot)
    # feature existed - CREATE TABLE IF NOT EXISTS above is a no-op against
    # an already-existing table, so already-deployed Postgres instances need
    # these columns added explicitly. Safe to run on every startup.
    conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS is_bargain_box INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS lot_card_count INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
        )
        """
    )
    # Password reset: a single-use, time-limited token emailed to the
    # account's address (see email_utils.py). token is the primary key
    # directly (a long random URL-safe string via secrets.token_urlsafe) -
    # no separate id needed since the token itself must already be
    # unguessable to be safe as a reset credential.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS offers (
            id TEXT PRIMARY KEY,
            card_slug TEXT NOT NULL,
            buyer_user_id TEXT NOT NULL,
            seller_user_id TEXT,
            amount_cents INTEGER,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
        )
        """
    )
    # Bargain Box lots: a buyer checks off multiple individually-listed
    # cards (must all belong to one seller) and SAVES that selection as a
    # standalone lot before making an offer on it - this is the persisted
    # object an offer is made against, rather than an offer just carrying a
    # raw list of card slugs. card_slugs is a JSON array (not a join table -
    # keeps this symmetric with the single-card `offers` table above and
    # avoids a migration-heavy schema for what's still a lightweight
    # feature). total_list_price_cents here is a snapshot at save time for
    # display; the actual 80% floor on an offer is re-checked against live
    # card prices at offer time (see make_lot_offer in main.py), in case a
    # seller edited a price after the lot was saved.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lots (
            id TEXT PRIMARY KEY,
            card_slugs TEXT NOT NULL,
            buyer_user_id TEXT NOT NULL,
            seller_user_id TEXT NOT NULL,
            total_list_price_cents INTEGER NOT NULL,
            created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
        )
        """
    )
    # Bargain Box lot offers: one combined price proposed on a *saved* lot
    # (see `lots` above). card_slugs/total_list_price_cents are copied onto
    # the offer at creation time so this table stays self-contained for
    # display (offers.html doesn't need to join back to `lots` to show
    # what's in it) - lot_id is kept alongside purely so a buyer's saved lot
    # and the offer(s) made against it can be traced back to each other.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lot_offers (
            id TEXT PRIMARY KEY,
            lot_id TEXT,
            card_slugs TEXT NOT NULL,
            buyer_user_id TEXT NOT NULL,
            seller_user_id TEXT NOT NULL,
            total_list_price_cents INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL,
            message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
        )
        """
    )
    # Migration for the lot_offers table as it existed before lots were a
    # separate saved object - already-deployed instances need this column
    # added explicitly (CREATE TABLE IF NOT EXISTS above is a no-op against
    # an existing table). Safe to run on every startup.
    conn.execute("ALTER TABLE lot_offers ADD COLUMN IF NOT EXISTS lot_id TEXT")
    conn.commit()

    # Demo/placeholder cards used to be seeded here on first run (16 fake
    # listings - Trout, Jeter, etc.) so the site wasn't empty before real
    # inventory existed. Thor asked (2026-08-08) for only real, actually-
    # uploaded cards to ever display. Real cards are always inserted with
    # is_user_submitted = 1 (see create_card in main.py); the old demo rows
    # were always inserted with is_user_submitted = 0 - so this delete is
    # precisely targeted and can never touch a real listing. Runs on every
    # startup - harmless/no-op once the demo rows are gone.
    conn.execute("DELETE FROM cards WHERE is_user_submitted = 0")
    conn.commit()

    # One-time cleanup (2026-08-08): removing the original JJ Wetherholt
    # listing at Thor's request to start inventory fresh - it was listed
    # under an account whose login email couldn't be confirmed (the
    # password-reset flow revealed no account exists under the expected
    # email), so it couldn't be removed through the normal authenticated
    # delete flow. Also clears any offers made on it so nothing orphaned
    # references a deleted card. Safe to leave here permanently - becomes a
    # no-op once the row is gone. Remove this block once confirmed cleared.
    conn.execute("DELETE FROM offers WHERE card_slug = 'jj-wetherholt'")
    conn.execute("DELETE FROM cards WHERE slug = 'jj-wetherholt'")
    conn.commit()

    conn.close()


# --- User account helpers ---

def create_user(email, password_hash):
    conn = get_connection()
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
        (user_id, email.strip().lower(), password_hash),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def get_user_by_email(email):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def update_user_password(user_id, new_password_hash):
    conn = get_connection()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_password_hash, user_id))
    conn.commit()
    conn.close()


# --- Password reset helpers ---

def create_password_reset(user_id, expires_at_iso):
    conn = get_connection()
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at_iso),
    )
    conn.commit()
    conn.close()
    return token


def get_password_reset(token):
    conn = get_connection()
    row = conn.execute("SELECT * FROM password_resets WHERE token = ?", (token,)).fetchone()
    conn.close()
    return row


def mark_password_reset_used(token):
    conn = get_connection()
    conn.execute("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# --- Offer helpers ---
# "Make an Offer" and "Contact Seller" are the same flow: message required,
# amount_cents optional (a plain inquiry has no price attached).

def create_offer(card_slug, buyer_user_id, seller_user_id, amount_cents, message):
    conn = get_connection()
    offer_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO offers (id, card_slug, buyer_user_id, seller_user_id, amount_cents, message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (offer_id, card_slug, buyer_user_id, seller_user_id, amount_cents, message),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def get_offers_received(seller_user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM offers WHERE seller_user_id = ? ORDER BY created_at DESC",
        (seller_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_offers_sent(buyer_user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM offers WHERE buyer_user_id = ? ORDER BY created_at DESC",
        (buyer_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_offer_by_id(offer_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def update_offer_status(offer_id, status):
    conn = get_connection()
    conn.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer_id))
    conn.commit()
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


# --- Lot offer helpers (Bargain Box: one combined offer across several cards) ---

def get_cards_by_slugs(slugs):
    """Fetch cards by a list of slugs - used to validate a lot offer (same
    seller, real cards, current price) before it's created."""
    if not slugs:
        return []
    conn = get_connection()
    placeholders = ",".join(["?"] * len(slugs))
    rows = conn.execute(
        f"SELECT slug, price_cents, user_id FROM cards WHERE slug IN ({placeholders})",
        tuple(slugs),
    ).fetchall()
    conn.close()
    return rows


def create_lot(card_slugs, buyer_user_id, seller_user_id, total_list_price_cents):
    conn = get_connection()
    lot_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO lots (id, card_slugs, buyer_user_id, seller_user_id, total_list_price_cents)
        VALUES (?, ?, ?, ?, ?)
        """,
        (lot_id, json.dumps(card_slugs), buyer_user_id, seller_user_id, total_list_price_cents),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    return row


def get_lot_by_id(lot_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)).fetchone()
    conn.close()
    return row


def create_lot_offer(lot_id, card_slugs, buyer_user_id, seller_user_id, total_list_price_cents, amount_cents, message):
    conn = get_connection()
    offer_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO lot_offers
            (id, lot_id, card_slugs, buyer_user_id, seller_user_id, total_list_price_cents, amount_cents, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            offer_id, lot_id, json.dumps(card_slugs), buyer_user_id, seller_user_id,
            total_list_price_cents, amount_cents, message,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM lot_offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def get_lot_offers_received(seller_user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lot_offers WHERE seller_user_id = ? ORDER BY created_at DESC",
        (seller_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_lot_offers_sent(buyer_user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM lot_offers WHERE buyer_user_id = ? ORDER BY created_at DESC",
        (buyer_user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_lot_offer_by_id(offer_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM lot_offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def update_lot_offer_status(offer_id, status):
    conn = get_connection()
    conn.execute("UPDATE lot_offers SET status = ? WHERE id = ?", (status, offer_id))
    conn.commit()
    row = conn.execute("SELECT * FROM lot_offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row

