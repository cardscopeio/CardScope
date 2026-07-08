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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from .database import get_connection, init_db, slugify

app = FastAPI(title="CardScope.io API")

# Allow the deployed static frontend (GitHub Pages + custom domain) and local
# dev servers to call this API from a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cardscope.io",
        "https://cardscopeio.github.io",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "*",  # TODO: narrow this once the frontend's final hosting is locked in
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


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


@app.post("/api/cards", status_code=201)
def create_card(card: CardIn):
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
             serial_number, is_user_submitted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            slug, card.player, card.year, card.brand, card.type, card.era,
            card.condition, int(round(card.price * 100)), card.emoji,
            card.description, card.manufacturer, int(card.autographed),
            int(card.numbered), card.serialNumber,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row_to_card(row)


@app.delete("/api/cards/{slug}", status_code=204)
def delete_card(slug: str):
    conn = get_connection()
    row = conn.execute("SELECT slug FROM cards WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Card not found")
    conn.execute("DELETE FROM cards WHERE slug = ?", (slug,))
    conn.commit()
    conn.close()
    return None


@app.get("/api/health")
def health():
    return {"status": "ok"}
