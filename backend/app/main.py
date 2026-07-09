"""
CardScope.io backend API.

Replaces the old localStorage-only approach: card listings are now stored
in a real SQLite database, visible to every visitor, not just the browser
that submitted them.

Run locally:
    cd "10 Backend"
    python3 -m uvicorn app.main:app --reload --port 8000

API shape matches what the frontend (cards-data.js) already expects from a
card object, so the frontend migration is a data-source swap, not a rewrite:
    { player, year, brand, type, era, condition, price, emoji, description,
      isUserSubmitted, dateAdded }
"""
import re
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from .database import get_connection, init_db, slugify, create_user, get_user_by_email, get_user_by_id
from .auth import hash_password, verify_password, create_access_token, decode_access_token

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="CardScope.io API")

# Frontend hosting is locked in (cardscope.io custom domain + GitHub Pages),
# so CORS is scoped to just those origins plus local dev servers - no more
# wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cardscope.io",
        "https://cardscopeio.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# --- Auth models & dependency ---

class UserRegister(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_looks_valid(cls, v):
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email address")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_long_enough(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    accessToken: str
    tokenType: str = "bearer"
    userId: str
    email: str


def row_to_user_public(row) -> dict:
    return {"id": row["id"], "email": row["email"], "createdAt": row["created_at"]}


def get_current_user(authorization: Optional[str] = Header(None)):
    """FastAPI dependency - requires a valid 'Authorization: Bearer <token>' header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


@app.post("/api/auth/register", status_code=201, response_model=TokenOut)
def register(payload: UserRegister):
    if get_user_by_email(payload.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    password_hash = hash_password(payload.password)
    user = create_user(payload.email, password_hash)
    token = create_access_token(user["id"])
    return {"accessToken": token, "userId": user["id"], "email": user["email"]}


@app.post("/api/auth/login", response_model=TokenOut)
def login(payload: UserLogin):
    user = get_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token(user["id"])
    return {"accessToken": token, "userId": user["id"], "email": user["email"]}


@app.get("/api/auth/me")
def read_current_user(current_user=Depends(get_current_user)):
    return row_to_user_public(current_user)


def row_to_card(row) -> dict:
    dollars = row["price_cents"] / 100
    return {
        "id": row["slug"],
        "player": row["player"],
        "year": row["year"],
        "brand": row["brand"],
        "type": row["type"],
        "era": row["era"],
        "condition": row["condition"],
        "price": f"${dollars:,.0f}" if dollars == int(dollars) else f"${dollars:,.2f}",
        "emoji": row["emoji"] or "⚾",
        "description": row["description"] or "",
        "manufacturer": row["manufacturer"],
        "autographed": bool(row["autographed"]),
        "numbered": bool(row["numbered"]),
        "serialNumber": row["serial_number"],
        "status": row["status"],
        "isUserSubmitted": bool(row["is_user_submitted"]),
        "dateAdded": row["date_added"],
        "frontImageUrl": row["front_image_url"],
        "backImageUrl": row["back_image_url"],
        "userId": row["user_id"],
    }


class CardIn(BaseModel):
    player: str
    year: str
    brand: str
    type: str
    era: str
    condition: Optional[str] = None
    price: float = Field(..., description="Price in dollars, e.g. 8750.00")
    emoji: str = "⚾"
    description: Optional[str] = ""
    manufacturer: Optional[str] = None
    autographed: bool = False
    numbered: bool = False
    serialNumber: Optional[str] = None
    frontImageUrl: Optional[str] = None
    backImageUrl: Optional[str] = None


@app.get("/api/cards")
def list_cards():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM cards ORDER BY is_user_submitted DESC, date_added DESC"
    ).fetchall()
    conn.close()
    return [row_to_card(r) for r in rows]


@app.get("/api/cards/{slug}")
def get_card(slug: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM cards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return row_to_card(row)


@app.get("/api/my-cards")
def list_my_cards(current_user=Depends(get_current_user)):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM cards WHERE user_id = ? ORDER BY date_added DESC",
        (current_user["id"],),
    ).fetchall()
    conn.close()
    return [row_to_card(r) for r in rows]


@app.post("/api/cards", status_code=201)
def create_card(card: CardIn, current_user=Depends(get_current_user)):
    slug = slugify(card.player)
    conn = get_connection()

    # If this player's slug already exists, disambiguate rather than
    # silently overwriting a different card (e.g. two different cards of
    # the same player).
    existing = conn.execute("SELECT slug FROM cards WHERE slug = ?", (slug,)).fetchone()
    if existing:
        suffix = 2
        base_slug = slug
        while conn.execute("SELECT slug FROM cards WHERE slug = ?", (f"{base_slug}-{suffix}",)).fetchone():
            suffix += 1
        slug = f"{base_slug}-{suffix}"

    conn.execute(
        """
        INSERT INTO cards
            (slug, player, year, brand, type, era, condition, price_cents,
             emoji, description, manufacturer, autographed, numbered,
             serial_number, is_user_submitted, front_image_url, back_image_url, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            slug, card.player, card.year, card.brand, card.type, card.era,
            card.condition, int(round(card.price * 100)), card.emoji,
            card.description, card.manufacturer, int(card.autographed),
            int(card.numbered), card.serialNumber,
            card.frontImageUrl, card.backImageUrl, current_user["id"],
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row_to_card(row)


@app.delete("/api/cards/{slug}", status_code=204)
def delete_card(slug: str, current_user=Depends(get_current_user)):
    conn = get_connection()
    row = conn.execute("SELECT slug, user_id FROM cards WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Card not found")
    if row["user_id"] != current_user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="You can only delete cards you listed")
    conn.execute("DELETE FROM cards WHERE slug = ?", (slug,))
    conn.commit()
    conn.close()
    return None


@app.get("/api/health")
def health():
    return {"status": "ok"}
