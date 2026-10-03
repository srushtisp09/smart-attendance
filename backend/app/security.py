from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def create_qr_token(session_id: int) -> str:
    """Short-lived signed token the teacher's screen shows as a QR code.
    The app re-requests a fresh one every ~15 s, so a screenshot sent to an absent friend expires fast."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=settings.QR_TOKEN_SECONDS)
    payload = {"typ": "qr", "sid": session_id, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_qr_token(token: str) -> int:
    """Return the session id, or raise jwt.ExpiredSignatureError / jwt.PyJWTError."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if payload.get("typ") != "qr":  # e.g. someone pasted a login token instead
        raise jwt.InvalidTokenError("not a QR token")
    return int(payload["sid"])
