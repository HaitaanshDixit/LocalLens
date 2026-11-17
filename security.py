from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

import config


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# Used when the email is unknown, so login takes about the same time either way
# and response timing doesn't reveal which emails are registered.
_DUMMY_HASH = hash_password("timing-equaliser-password")


def verify_dummy(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Return the user id if the token is valid and unexpired, else None."""
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=[config.JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError:
        return None
    return payload.get("sub")