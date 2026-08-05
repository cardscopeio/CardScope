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

    # Seed with the original 16 demo cards on first run only, so re-deploys
    # don't duplicate rows.
    count_row = conn.execute("SELECT COUNT(*) as count FROM cards").fetchone()
    if count_row["count"] == 0:
        seed_demo_cards(conn)

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


DEMO_CARDS = [
    ("Mike Trout", "2011", "Topps Chrome", "Rookie Autograph", "modern", "PSA 10", 875000,
     "One of the most sought-after modern baseball cards, this Mike Trout rookie autograph from 2011 Topps Chrome represents the emergence of baseball's greatest player of his generation. Graded PSA 10, this card is in pristine gem mint condition with perfect centering, sharp corners, and a flawless signature."),
    ("Ronald Acuña Jr.", "2018", "Topps Chrome", "Rookie Autograph", "modern", "PSA 9", 220000,
     "Ronald Acuña Jr.'s explosive debut season made this 2018 Topps Chrome rookie autograph an instant classic. Graded PSA 9, this card features the young superstar's on-card signature and showcases his early promise as one of baseball's most dynamic players."),
    ("Derek Jeter", "1993", "SP", "Rookie Card", "modern", "PSA 9", 145000,
     "The Captain's flagship rookie card from 1993 SP is one of the most iconic cards of the 1990s. This PSA 9 example captures Derek Jeter at the beginning of his legendary career with the New York Yankees, before his five World Series championships and 3,000+ hits."),
    ("Shohei Ohtani", "2018", "Topps Chrome", "Rookie Card", "modern", "PSA 10", 550000,
     "A true unicorn in baseball history, Shohei Ohtani's 2018 Topps Chrome rookie card in PSA 10 represents the only player to excel as both an elite pitcher and power hitter in the modern era. This gem mint card has become one of the most valuable modern rookies."),
    ("Mickey Mantle", "1952", "Topps", "Rookie Card", "vintage", "PSA 5", 8500000,
     "The holy grail of baseball cards. Mickey Mantle's 1952 Topps rookie is the most iconic card in the hobby, featuring the Yankees legend in his second year. Even in PSA 5 condition, this card commands massive premiums due to its legendary status and the difficulty of finding centered examples."),
    ("Jackie Robinson", "1948", "Leaf", "Rookie Card", "vintage", "PSA 4", 4500000,
     "More than just a baseball card, this 1948 Leaf Jackie Robinson rookie represents a pivotal moment in American history. Robinson broke baseball's color barrier in 1947, and this card from his second season is one of the most historically significant cards in the hobby."),
    ("Ken Griffey Jr.", "1989", "Upper Deck", "Rookie Card", "modern", "PSA 10", 320000,
     "The most iconic card of the junk wax era, Ken Griffey Jr.'s 1989 Upper Deck #1 rookie card in PSA 10 remains highly desirable. Junior's sweet swing and infectious smile made him baseball's most marketable player of the 1990s, and this card launched Upper Deck as a premium brand."),
    ("Willie Mays", "1952", "Topps", "Rookie Card", "vintage", "PSA 6", 2850000,
     "The Say Hey Kid's 1952 Topps rookie card is one of the most important vintage cards in existence. Willie Mays is widely considered one of the five greatest players ever, and this PSA 6 example from the legendary 1952 Topps set is a museum-quality piece of baseball history."),
    ("Vladimir Guerrero Jr.", "2019", "Topps Chrome", "Rookie Autograph", "modern", "PSA 10", 185000,
     "Following in his Hall of Fame father's footsteps, Vladimir Guerrero Jr.'s 2019 Topps Chrome rookie autograph in PSA 10 captures one of baseball's most exciting young sluggers. His powerful swing and consistent production make this a strong modern investment piece."),
    ("Roberto Clemente", "1955", "Topps", "Rookie Card", "vintage", "PSA 5", 1850000,
     "Roberto Clemente's 1955 Topps rookie card honors one of baseball's most beloved humanitarian players. The Hall of Famer's tragic death while delivering earthquake relief supplies has made his cards even more meaningful to collectors. This PSA 5 is a cherished piece of baseball heritage."),
    ("Fernando Tatis Jr.", "2019", "Topps Chrome", "Rookie Autograph", "modern", "PSA 9", 120000,
     "Before controversy, Fernando Tatis Jr. burst onto the scene as one of baseball's most electrifying talents. This 2019 Topps Chrome rookie autograph in PSA 9 captures his tremendous potential and remains a polarizing but intriguing piece in the modern market."),
    ("Hank Aaron", "1954", "Topps", "Rookie Card", "vintage", "PSA 6", 3200000,
     "Hammerin' Hank's 1954 Topps rookie card is a cornerstone of any serious vintage collection. Aaron's 755 home runs stood as the all-time record for decades, and his dignified pursuit of excellence on and off the field makes this PSA 6 rookie a prized possession."),
    ("Bryce Harper", "2012", "Bowman Chrome", "Prospect Autograph", "modern", "PSA 10", 240000,
     "The most hyped prospect since LeBron James, Bryce Harper's 2012 Bowman Chrome prospect autograph in PSA 10 captures the phenom before his MLB debut. His 2015 MVP season and consistent star power have kept this card relevant in the modern market."),
    ("Sandy Koufax", "1955", "Topps", "Rookie Card", "vintage", "PSA 5", 2400000,
     "Sandy Koufax's 1955 Topps rookie card represents one of the greatest pitchers who ever lived. His dominant stretch from 1963-1966 included three Cy Young awards and four no-hitters. This PSA 5 rookie is a blue-chip investment in baseball history."),
    ("Juan Soto", "2018", "Topps Chrome", "Rookie Autograph", "modern", "PSA 10", 195000,
     "Juan Soto's advanced hitting approach and patient eye at the plate made him an instant star. This 2018 Topps Chrome rookie autograph in PSA 10 gem mint condition captures one of the game's most disciplined young hitters and a perennial MVP candidate."),
    ("Pete Rose", "1963", "Topps", "Rookie Card", "vintage", "PSA 7", 850000,
     "Charlie Hustle's 1963 Topps rookie card remains popular despite his controversial ban from baseball. Pete Rose's 4,256 career hits still stand as the all-time record, and this PSA 7 rookie card from the classic 1963 set is a snapshot of baseball's Hit King."),
]


def seed_demo_cards(conn):
    for player, year, brand, ctype, era, condition, price_cents, description in DEMO_CARDS:
        slug = slugify(player)
        conn.execute(
            """
            INSERT INTO cards
                (slug, player, year, brand, type, era, condition, price_cents, description, is_user_submitted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT (slug) DO NOTHING
            """,
            (slug, player, year, brand, ctype, era, condition, price_cents, description),
        )
    conn.commit()
