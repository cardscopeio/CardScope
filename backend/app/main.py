"""
CardScope.io backend API.

Card listings, accounts, and offers are stored in a real Postgres database
(Neon), visible to every visitor - not just the browser that submitted them,
and not wiped every time the backend redeploys (see database.py for why
SQLite-on-Render's-free-tier didn't actually persist data).

Run locally (requires a DATABASE_URL env var pointing at a Postgres/Neon
instance - see database.py):
    cd backend
    export DATABASE_URL="postgresql://..."
    python3 -m uvicorn app.main:app --reload --port 8000

API shape matches what the frontend (cards-data.js) already expects from a
card object, so the frontend migration is a data-source swap, not a rewrite:
    { player, year, brand, type, era, condition, price, emoji, description,
      isUserSubmitted, dateAdded }
"""
import json
import re
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

from .database import (
    get_connection, init_db, slugify, create_user, get_user_by_email, get_user_by_id,
    create_offer, get_offers_received, get_offers_sent, get_offer_by_id, update_offer_status,
    get_cards_by_slugs, create_lot, get_lot_by_id, create_lot_offer,
    get_lot_offers_received, get_lot_offers_sent, get_lot_offer_by_id, update_lot_offer_status,
)
from .auth import hash_password, verify_password, create_access_token, decode_access_token

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Bargain Box lot offers can't undercut the combined individual list price by
# more than this - keeps buyers from bundling cards just to lowball a
# seller. Mirrored in the frontend (cards-data.js LOT_OFFER_MIN_FRACTION) for
# client-side guidance, but this is the number that's actually enforced.
LOT_OFFER_MIN_FRACTION = 0.8

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
        "isBargainBox": bool(row["is_bargain_box"]),
        "lotCardCount": row["lot_card_count"],
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
    isBargainBox: bool = False
    lotCardCount: Optional[int] = Field(
        None, description="Number of cards included in this lot - only meaningful when isBargainBox is true"
    )


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
             serial_number, is_user_submitted, front_image_url, back_image_url, user_id,
             is_bargain_box, lot_card_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """,
        (
            slug, card.player, card.year, card.brand, card.type, card.era,
            card.condition, int(round(card.price * 100)), card.emoji,
            card.description, card.manufacturer, int(card.autographed),
            int(card.numbered), card.serialNumber,
            card.frontImageUrl, card.backImageUrl, current_user["id"],
            int(card.isBargainBox), card.lotCardCount,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM cards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row_to_card(row)


@app.put("/api/cards/{slug}")
def update_card(slug: str, card: CardIn, current_user=Depends(get_current_user)):
    conn = get_connection()
    row = conn.execute("SELECT slug, user_id FROM cards WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Card not found")
    if row["user_id"] != current_user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="You can only edit cards you listed")

    # Slug (the primary key / URL) never changes on edit, even if the player
    # name is corrected - keeps the listing's URL stable.
    conn.execute(
        """
        UPDATE cards SET
            player = ?, year = ?, brand = ?, type = ?, era = ?, condition = ?,
            price_cents = ?, emoji = ?, description = ?, manufacturer = ?,
            autographed = ?, numbered = ?, serial_number = ?,
            front_image_url = ?, back_image_url = ?,
            is_bargain_box = ?, lot_card_count = ?
        WHERE slug = ?
        """,
        (
            card.player, card.year, card.brand, card.type, card.era,
            card.condition, int(round(card.price * 100)), card.emoji,
            card.description, card.manufacturer, int(card.autographed),
            int(card.numbered), card.serialNumber,
            card.frontImageUrl, card.backImageUrl,
            int(card.isBargainBox), card.lotCardCount, slug,
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


# --- Offers ("Make an Offer" / "Contact Seller" - one combined flow) ---

class OfferIn(BaseModel):
    amount: Optional[float] = Field(None, description="Offer amount in dollars - optional, omit for a plain inquiry")
    message: str


class OfferStatusIn(BaseModel):
    status: str  # "accepted" or "declined"

    @field_validator("status")
    @classmethod
    def status_is_valid(cls, v):
        if v not in ("accepted", "declined"):
            raise ValueError('status must be "accepted" or "declined"')
        return v


def row_to_offer(row) -> dict:
    dollars = row["amount_cents"] / 100 if row["amount_cents"] is not None else None
    return {
        "id": row["id"],
        "cardSlug": row["card_slug"],
        "buyerUserId": row["buyer_user_id"],
        "sellerUserId": row["seller_user_id"],
        "amount": f"${dollars:,.0f}" if dollars is not None and dollars == int(dollars)
                  else (f"${dollars:,.2f}" if dollars is not None else None),
        "message": row["message"],
        "status": row["status"],
        "createdAt": row["created_at"],
    }


@app.post("/api/cards/{slug}/offers", status_code=201)
def make_offer(slug: str, offer: OfferIn, current_user=Depends(get_current_user)):
    conn = get_connection()
    card = conn.execute("SELECT slug, user_id FROM cards WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    if card["user_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="You can't make an offer on your own listing")

    amount_cents = int(round(offer.amount * 100)) if offer.amount is not None else None
    row = create_offer(slug, current_user["id"], card["user_id"], amount_cents, offer.message)
    return row_to_offer(row)


@app.get("/api/my-offers/received")
def list_offers_received(current_user=Depends(get_current_user)):
    rows = get_offers_received(current_user["id"])
    return [row_to_offer(r) for r in rows]


@app.get("/api/my-offers/sent")
def list_offers_sent(current_user=Depends(get_current_user)):
    rows = get_offers_sent(current_user["id"])
    return [row_to_offer(r) for r in rows]


@app.patch("/api/offers/{offer_id}")
def respond_to_offer(offer_id: str, payload: OfferStatusIn, current_user=Depends(get_current_user)):
    offer = get_offer_by_id(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer["seller_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only the seller can respond to this offer")
    row = update_offer_status(offer_id, payload.status)
    return row_to_offer(row)


# --- Lots + Lot Offers (Bargain Box: one combined offer across several cards) ---
#
# Two steps, not one: a buyer first SAVES a selection of 2+ individually-
# listed cards (must all belong to the same seller) as a standalone `lot`,
# then makes an offer against that saved lot's id - an offer is never built
# directly from a raw list of card slugs. This gives the lot a durable
# identity (so, e.g., a declined offer doesn't force re-picking the same
# cards to try again) independent of the offer(s) made against it.
#
# The offer amount must be at least LOT_OFFER_MIN_FRACTION (80%) of the
# combined list price - re-checked against CURRENT card prices at offer
# time (not the lot's save-time snapshot), since a seller could have edited
# a price in between. This is a hard server-side floor, not just a UI hint -
# no lowball lot offer can be submitted at all. Beyond that, it's just the
# normal offer flow: the seller still manually Accepts/Declines in
# offers.html, same as any single-card offer - this feature only guards
# against outlandish opening numbers, it doesn't auto-accept anything.

def _fmt_usd(dollars: float) -> str:
    return f"${dollars:,.0f}" if dollars == int(dollars) else f"${dollars:,.2f}"


class LotIn(BaseModel):
    cardSlugs: List[str]

    @field_validator("cardSlugs")
    @classmethod
    def at_least_two_distinct_cards(cls, v):
        if len(v) < 2:
            raise ValueError("A lot needs at least 2 cards - use the regular offer flow for a single card")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate cards selected")
        return v


def row_to_lot(row) -> dict:
    total_dollars = row["total_list_price_cents"] / 100
    return {
        "id": row["id"],
        "cardSlugs": json.loads(row["card_slugs"]),
        "buyerUserId": row["buyer_user_id"],
        "sellerUserId": row["seller_user_id"],
        "totalListPrice": _fmt_usd(total_dollars),
        "minLotOffer": _fmt_usd(total_dollars * LOT_OFFER_MIN_FRACTION),
        "createdAt": row["created_at"],
    }


@app.post("/api/lots", status_code=201)
def save_lot(payload: LotIn, current_user=Depends(get_current_user)):
    rows = get_cards_by_slugs(payload.cardSlugs)

    found_slugs = {r["slug"] for r in rows}
    missing = [s for s in payload.cardSlugs if s not in found_slugs]
    if missing:
        raise HTTPException(status_code=404, detail=f"Card(s) not found: {', '.join(missing)}")

    seller_ids = {r["user_id"] for r in rows}
    if len(seller_ids) != 1:
        raise HTTPException(status_code=400, detail="All cards in a lot must be listed by the same seller")
    seller_user_id = seller_ids.pop()

    if seller_user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="You can't build a lot from your own listings")

    total_list_price_cents = sum(r["price_cents"] for r in rows)
    row = create_lot(payload.cardSlugs, current_user["id"], seller_user_id, total_list_price_cents)
    return row_to_lot(row)


@app.get("/api/lots/{lot_id}")
def get_lot(lot_id: str, current_user=Depends(get_current_user)):
    row = get_lot_by_id(lot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lot not found")
    if current_user["id"] not in (row["buyer_user_id"], row["seller_user_id"]):
        raise HTTPException(status_code=403, detail="You don't have access to this lot")
    return row_to_lot(row)


class LotOfferIn(BaseModel):
    lotId: str
    amount: float = Field(..., description="Proposed price in dollars for the whole lot, not per card")
    message: Optional[str] = ""


def row_to_lot_offer(row) -> dict:
    total_dollars = row["total_list_price_cents"] / 100
    amount_dollars = row["amount_cents"] / 100
    return {
        "id": row["id"],
        "lotId": row["lot_id"],
        "cardSlugs": json.loads(row["card_slugs"]),
        "buyerUserId": row["buyer_user_id"],
        "sellerUserId": row["seller_user_id"],
        "totalListPrice": _fmt_usd(total_dollars),
        "amount": _fmt_usd(amount_dollars),
        "percentOfList": round((amount_dollars / total_dollars) * 100) if total_dollars else None,
        "message": row["message"],
        "status": row["status"],
        "createdAt": row["created_at"],
    }


@app.post("/api/lot-offers", status_code=201)
def make_lot_offer(payload: LotOfferIn, current_user=Depends(get_current_user)):
    lot = get_lot_by_id(payload.lotId)
    if lot is None:
        raise HTTPException(status_code=404, detail="Lot not found - save a lot first via POST /api/lots")
    if lot["buyer_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="You can only make offers on lots you've saved")

    # Re-check current prices/ownership rather than trusting the lot's
    # save-time snapshot - a seller could have edited a price (or the
    # listing could be gone) since the lot was saved, and the 80% floor
    # should reflect reality now, not whenever the lot was built.
    card_slugs = json.loads(lot["card_slugs"])
    rows = get_cards_by_slugs(card_slugs)
    found_slugs = {r["slug"] for r in rows}
    missing = [s for s in card_slugs if s not in found_slugs]
    if missing:
        raise HTTPException(status_code=404, detail=f"Card(s) no longer available: {', '.join(missing)}")
    seller_ids = {r["user_id"] for r in rows}
    if len(seller_ids) != 1 or seller_ids.pop() != lot["seller_user_id"]:
        raise HTTPException(status_code=400, detail="This lot's cards have changed sellers - save a new lot")

    total_list_price_cents = sum(r["price_cents"] for r in rows)
    amount_cents = int(round(payload.amount * 100))
    min_amount_cents = int(round(total_list_price_cents * LOT_OFFER_MIN_FRACTION))
    if amount_cents < min_amount_cents:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Lot offers must be at least {int(LOT_OFFER_MIN_FRACTION * 100)}% of the combined list price "
                f"(minimum ${min_amount_cents / 100:,.2f} for this lot)"
            ),
        )

    row = create_lot_offer(
        lot["id"], card_slugs, current_user["id"], lot["seller_user_id"],
        total_list_price_cents, amount_cents, payload.message,
    )
    return row_to_lot_offer(row)


@app.get("/api/my-lot-offers/received")
def list_lot_offers_received(current_user=Depends(get_current_user)):
    rows = get_lot_offers_received(current_user["id"])
    return [row_to_lot_offer(r) for r in rows]


@app.get("/api/my-lot-offers/sent")
def list_lot_offers_sent(current_user=Depends(get_current_user)):
    rows = get_lot_offers_sent(current_user["id"])
    return [row_to_lot_offer(r) for r in rows]


@app.patch("/api/lot-offers/{offer_id}")
def respond_to_lot_offer(offer_id: str, payload: OfferStatusIn, current_user=Depends(get_current_user)):
    offer = get_lot_offer_by_id(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Lot offer not found")
    if offer["seller_user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Only the seller can respond to this lot offer")
    row = update_lot_offer_status(offer_id, payload.status)
    return row_to_lot_offer(row)


@app.get("/api/health")
def health():
    return {"status": "ok"}
