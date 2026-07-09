"""
Authentication for CardScope.io: password hashing + JWT session tokens.

Kept deliberately simple (stateless JWTs, no refresh-token rotation, no email
verification/password reset flow yet) - this is a real but early-stage
marketplace, not a bank. Revisit if/when password reset or email verification
becomes a real need.
"""
import os
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

# IMPORTANT: set a real JWT_SECRET_KEY environment variable on Render.
# This fallback is NOT secure for production - it's only here so local dev
# doesn't crash if the env var isn't set. If you see this warning in
# production logs, the secret has not been configured.
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = "INSECURE-DEV-ONLY-SECRET-DO-NOT-USE-IN-PRODUCTION"
    print("WARNING: JWT_SECRET_KEY is not set. Using an insecure default. "
          "Set a real JWT_SECRET_KEY environment variable on Render.")

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_DAYS = 30


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str):
    """Returns the user_id from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
