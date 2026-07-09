"""
SQLite setup for CardScope.io's backend.

Deliberately plain sqlite3 (stdlib) instead of an ORM - the schema is small
and this keeps the dependency list (and thing-to-learn list) minimal.
"""
import sqlite3
import os
import re
import uuid

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "cardscope.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
            date_added TEXT DEFAULT (datetime('now')),
            front_image_url TEXT,
            back_image_url TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()

    # Migrate existing databases created before front/back image support was
    # added, so a re-deploy doesn't wipe/break on the new columns.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(cards)").fetchall()}
    if "front_image_url" not in existing_cols:
        conn.execute("ALTER TABLE cards ADD COLUMN front_image_url TEXT")
    if "back_image_url" not in existing_cols:
        conn.execute("ALTER TABLE cards ADD COLUMN back_image_url TEXT")
    if "user_id" not in existing_cols:
        # Nullable - existing demo cards and any pre-accounts listings have
        # no owner. Only newly-created cards get a real user_id going forward.
        conn.execute("ALTER TABLE cards ADD COLUMN user_id TEXT")
    conn.commit()

    # Seed with the original 16 demo cards on first run only, so re-deploys
    # don't duplicate rows.
    count = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    if count == 0:
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
            INSERT OR IGNORE INTO cards
                (slug, player, year, brand, type, era, condition, price_cents, description, is_user_submitted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (slug, player, year, brand, ctype, era, condition, price_cents, description),
        )
    conn.commit()
