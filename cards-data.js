// CardScope.io API client.
//
// All card data now lives in the backend (see "10 Backend/" in the vault
// project) instead of a hardcoded array + localStorage. This replaces the
// old version of this file that duplicated demo cards and only knew about
// listings saved in the current browser's localStorage - meaning a card
// someone listed was invisible to every other visitor. Now every listing
// goes through the API and is visible to everyone immediately.
//
// Requires config.js (defines API_BASE_URL) to be loaded first.

// --- Theme (dark default / light, user preference) ---
// The actual instant-apply-before-paint logic is a tiny inline script in
// each page's <head> (has to run before body renders, so it can't wait for
// this file to load) - these are just the toggle button's click handler and
// the shared "what theme is active" helpers, used across every page.
const THEME_STORAGE_KEY = "cardscope_theme";

function getTheme() {
    return localStorage.getItem(THEME_STORAGE_KEY) || "dark";
}

function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    updateThemeToggleButtons();
}

function toggleTheme() {
    setTheme(getTheme() === "dark" ? "light" : "dark");
}

function updateThemeToggleButtons() {
    const isDark = getTheme() === "dark";
    document.querySelectorAll(".theme-toggle-btn").forEach((btn) => {
        btn.textContent = isDark ? "☀️" : "🌙";
        btn.title = isDark ? "Switch to light mode" : "Switch to dark mode";
    });
}

// Re-sync on pageshow, not just on initial load. Browsers can restore a
// page from the back/forward cache (bfcache) when you hit Back - that
// restores the DOM exactly as it was when you left the page, WITHOUT
// re-running the inline <head> script that reads the current theme. Without
// this, hitting Back after changing the theme on another page shows the
// stale theme this page had last time you were on it, not your current
// preference. Safe to run unconditionally (not just when event.persisted is
// true) - re-applying the same theme is a harmless no-op.
window.addEventListener("pageshow", function () {
    setTheme(getTheme());
});

async function fetchAllCards() {
    const res = await fetch(`${API_BASE_URL}/api/cards`);
    if (!res.ok) throw new Error(`Failed to load cards (${res.status})`);
    return res.json();
}

async function fetchCardById(id) {
    const res = await fetch(`${API_BASE_URL}/api/cards/${encodeURIComponent(id)}`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Failed to load card (${res.status})`);
    return res.json();
}

async function submitCard(cardData) {
    const res = await fetch(`${API_BASE_URL}/api/cards`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify(cardData),
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to submit card (${res.status})`);
    return res.json();
}

async function updateCard(id, cardData) {
    const res = await fetch(`${API_BASE_URL}/api/cards/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify(cardData),
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to update card (${res.status})`);
    return res.json();
}

async function deleteCardById(id) {
    const res = await fetch(`${API_BASE_URL}/api/cards/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok && res.status !== 404) throw new Error(`Failed to delete card (${res.status})`);
}

async function fetchMyCards() {
    const res = await fetch(`${API_BASE_URL}/api/my-cards`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to load your cards (${res.status})`);
    return res.json();
}

// --- Offers ("Make an Offer" / "Contact Seller" - one combined flow) ---

async function makeOffer(cardId, { amount, message }) {
    const res = await fetch(`${API_BASE_URL}/api/cards/${encodeURIComponent(cardId)}/offers`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ amount: amount ?? null, message }),
    });
    if (res.status === 401) throw new AuthRequiredError();
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Failed to send offer (${res.status})`);
    return data;
}

async function fetchOffersReceived() {
    const res = await fetch(`${API_BASE_URL}/api/my-offers/received`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to load offers (${res.status})`);
    return res.json();
}

async function fetchOffersSent() {
    const res = await fetch(`${API_BASE_URL}/api/my-offers/sent`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to load offers (${res.status})`);
    return res.json();
}

async function respondToOffer(offerId, status) {
    const res = await fetch(`${API_BASE_URL}/api/offers/${encodeURIComponent(offerId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ status }),
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to respond to offer (${res.status})`);
    return res.json();
}

// --- Lots + Lot Offers (Bargain Box: one combined offer across several cards) ---
// The buyer first SAVES a selection of individually-listed cards (all from
// the same seller) as a standalone lot, then makes an offer against that
// saved lot's id - an offer is never built directly from a raw card list.
// LOT_OFFER_MIN_FRACTION is mirrored here purely so the UI can guide the
// buyer to a valid number before submitting - the backend (main.py
// LOT_OFFER_MIN_FRACTION) is the real enforcement point and re-checks
// against current card prices at offer time regardless of what the client
// sends.
const LOT_OFFER_MIN_FRACTION = 0.8;

async function saveLot(cardSlugs) {
    const res = await fetch(`${API_BASE_URL}/api/lots`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ cardSlugs }),
    });
    if (res.status === 401) throw new AuthRequiredError();
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Failed to save lot (${res.status})`);
    return data;
}

async function fetchLot(lotId) {
    const res = await fetch(`${API_BASE_URL}/api/lots/${encodeURIComponent(lotId)}`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Failed to load lot (${res.status})`);
    return res.json();
}

async function makeLotOffer(lotId, { amount, message }) {
    const res = await fetch(`${API_BASE_URL}/api/lot-offers`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ lotId, amount, message: message || "" }),
    });
    if (res.status === 401) throw new AuthRequiredError();
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Failed to send lot offer (${res.status})`);
    return data;
}

async function fetchLotOffersReceived() {
    const res = await fetch(`${API_BASE_URL}/api/my-lot-offers/received`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to load lot offers (${res.status})`);
    return res.json();
}

async function fetchLotOffersSent() {
    const res = await fetch(`${API_BASE_URL}/api/my-lot-offers/sent`, {
        headers: { ...authHeader() },
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to load lot offers (${res.status})`);
    return res.json();
}

async function respondToLotOffer(offerId, status) {
    const res = await fetch(`${API_BASE_URL}/api/lot-offers/${encodeURIComponent(offerId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ status }),
    });
    if (res.status === 401) throw new AuthRequiredError();
    if (!res.ok) throw new Error(`Failed to respond to lot offer (${res.status})`);
    return res.json();
}

// --- Auth ---
// Sessions are a JWT stored in localStorage - simple and fine for a
// marketplace at this stage. No refresh-token rotation, no password-reset
// flow yet (see backend/app/auth.py for the same note).

const AUTH_TOKEN_KEY = "cardscope_auth_token";
const AUTH_EMAIL_KEY = "cardscope_auth_email";
const AUTH_USER_ID_KEY = "cardscope_auth_user_id";

class AuthRequiredError extends Error {
    constructor() {
        super("Authentication required");
        this.name = "AuthRequiredError";
    }
}

function authHeader() {
    const token = getAuthToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
}

function getAuthToken() {
    return localStorage.getItem(AUTH_TOKEN_KEY);
}

function getAuthEmail() {
    return localStorage.getItem(AUTH_EMAIL_KEY);
}

function getAuthUserId() {
    return localStorage.getItem(AUTH_USER_ID_KEY);
}

function isLoggedIn() {
    return !!getAuthToken();
}

function saveSession(accessToken, email, userId) {
    localStorage.setItem(AUTH_TOKEN_KEY, accessToken);
    localStorage.setItem(AUTH_EMAIL_KEY, email);
    localStorage.setItem(AUTH_USER_ID_KEY, userId);
}

function logout() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_EMAIL_KEY);
    localStorage.removeItem(AUTH_USER_ID_KEY);
}

async function registerAccount(email, password) {
    const res = await fetch(`${API_BASE_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Registration failed (${res.status})`);
    saveSession(data.accessToken, data.email, data.userId);
    return data;
}

async function loginAccount(email, password) {
    const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Login failed (${res.status})`);
    saveSession(data.accessToken, data.email, data.userId);
    return data;
}

// Updates any nav element with id="authNavSlot" to show Sign In/Up or
// My Cards/Log Out depending on session state. Call on every page's load.
function renderAuthNav() {
    const slot = document.getElementById("authNavSlot");
    if (!slot) return;
    if (isLoggedIn()) {
        slot.innerHTML = `
            <a href="manage-cards.html">My Cards</a>
            <a href="offers.html">My Offers</a>
            <a href="#" onclick="logout(); window.location.href='index.html'; return false;">Log Out (${getAuthEmail()})</a>
        `;
    } else {
        slot.innerHTML = `<a href="login.html">Sign In / Sign Up</a>`;
    }
}

// Renders the front/back hover-flip markup for a card (see card-flip.css).
// Falls back to a plain emoji box when no images are set, so demo cards
// without real photos still render exactly as before.
function cardImageMarkup(card, emojiFontSize) {
    if (!card.frontImageUrl) {
        return `<div class="card-flip-image" style="display:flex;align-items:center;justify-content:center;font-size:${emojiFontSize};">${card.emoji || '⚾'}</div>`;
    }
    const backImg = card.backImageUrl
        ? `<img class="card-flip-back" src="${card.backImageUrl}" alt="${card.player} (back)">`
        : '';
    return `
        <div class="card-flip-image">
            <img class="card-flip-front" src="${card.frontImageUrl}" alt="${card.player}">
            ${backImg}
        </div>
    `;
}

// Touch devices have no :hover, so tap toggles the .flipped class instead.
// Safe to call repeatedly after re-rendering a card list.
function initCardFlipTouchSupport(container) {
    (container || document).querySelectorAll('.card-flip-image').forEach((el) => {
        if (el.dataset.flipBound) return;
        el.dataset.flipBound = 'true';
        el.addEventListener('click', (e) => {
            if (window.matchMedia('(hover: none)').matches) {
                el.classList.toggle('flipped');
                e.stopPropagation();
            }
        });
    });
}
