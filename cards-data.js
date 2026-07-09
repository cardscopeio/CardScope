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

// --- Auth ---
// Sessions are a JWT stored in localStorage - simple and fine for a
// marketplace at this stage. No refresh-token rotation, no password-reset
// flow yet (see backend/app/auth.py for the same note).

const AUTH_TOKEN_KEY = "cardscope_auth_token";
const AUTH_EMAIL_KEY = "cardscope_auth_email";

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

function isLoggedIn() {
    return !!getAuthToken();
}

function saveSession(accessToken, email) {
    localStorage.setItem(AUTH_TOKEN_KEY, accessToken);
    localStorage.setItem(AUTH_EMAIL_KEY, email);
}

function logout() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_EMAIL_KEY);
}

async function registerAccount(email, password) {
    const res = await fetch(`${API_BASE_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Registration failed (${res.status})`);
    saveSession(data.accessToken, data.email);
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
    saveSession(data.accessToken, data.email);
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
