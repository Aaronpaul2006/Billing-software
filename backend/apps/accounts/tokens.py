"""Access tokens (JWT) and refresh tokens (opaque).

Access token claims (docs/02-api-design.md §2): sub (user), tid (tenant),
role, sid (session family), amr (how the user authenticated), plus iss,
iat, exp and typ; pid (the client) for role CLIENT, and only then.
Verification pins the algorithm and requires every claim.
"""

import hashlib
import secrets
import uuid
from collections.abc import Iterable
from datetime import datetime

import jwt
from django.conf import settings
from django.utils import timezone

from apps.core.tenancy import Principal

ALGORITHM = "HS256"
ACCESS = "access"
MFA_CHALLENGE = "mfa_challenge"
TOTP, EMAIL = "totp", "email"  # second-factor methods of an MFA challenge
CLIENT = "CLIENT"
REQUIRED_ACCESS_CLAIMS = ["iss", "iat", "exp", "sub", "tid", "role", "sid", "amr", "typ"]


class InvalidToken(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code  # "invalid_token" | "token_expired"


def _encode(payload: dict[str, object]) -> str:
    return jwt.encode(
        payload, settings.JWT_SIGNING_KEY, algorithm=ALGORITHM, headers={"kid": settings.JWT_KEY_ID}
    )


def _decode(token: str, required: list[str]) -> dict[str, object]:
    try:
        return jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[ALGORITHM],  # never trust the token's own "alg"
            issuer=settings.JWT_ISSUER,
            options={"require": required},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidToken("token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("invalid_token") from exc


def issue_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    session_id: uuid.UUID,
    amr: Iterable[str],
    party_id: uuid.UUID | None = None,
) -> tuple[str, datetime]:
    if (role == CLIENT) != (party_id is not None):
        raise ValueError("a CLIENT token names its party; no other role does")
    now = timezone.now()
    expires_at = now + settings.ACCESS_TOKEN_TTL
    claims: dict[str, object] = {
        "iss": settings.JWT_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": ACCESS,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role,
        "sid": str(session_id),
        "amr": sorted(set(amr)),
    }
    if party_id is not None:
        claims["pid"] = str(party_id)
    return _encode(claims), expires_at


def verify_access_token(token: str) -> Principal:
    claims = _decode(token, REQUIRED_ACCESS_CLAIMS)
    if claims.get("typ") != ACCESS:
        raise InvalidToken("invalid_token")  # e.g. an MFA challenge token
    if (claims["role"] == CLIENT) != ("pid" in claims):
        raise InvalidToken("invalid_token")
    try:
        return Principal(
            user_id=uuid.UUID(str(claims["sub"])),
            tenant_id=uuid.UUID(str(claims["tid"])),
            role=str(claims["role"]),
            session_id=uuid.UUID(str(claims["sid"])),
            amr=frozenset(str(m) for m in claims["amr"]),  # type: ignore[attr-defined]
            party_id=uuid.UUID(str(claims["pid"])) if "pid" in claims else None,
        )
    except (ValueError, TypeError) as exc:
        raise InvalidToken("invalid_token") from exc


def issue_mfa_challenge(user_id: uuid.UUID, method: str = TOTP) -> str:
    """Proof that the password step succeeded; exchanged with a code: from the
    authenticator app (method "totp") or emailed for this sign-in ("email")."""
    now = timezone.now()
    ttl = settings.EMAIL_CODE_TTL if method == EMAIL else settings.MFA_CHALLENGE_TTL
    return _encode(
        {
            "iss": settings.JWT_ISSUER,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "typ": MFA_CHALLENGE,
            "sub": str(user_id),
            "method": method,
        }
    )


def verify_mfa_challenge(token: str) -> tuple[uuid.UUID, str]:
    """(user id, method) of a valid challenge."""
    claims = _decode(token, ["iss", "iat", "exp", "sub", "typ", "method"])
    if claims.get("typ") != MFA_CHALLENGE or claims["method"] not in (TOTP, EMAIL):
        raise InvalidToken("invalid_token")
    try:
        return uuid.UUID(str(claims["sub"])), str(claims["method"])
    except ValueError as exc:
        raise InvalidToken("invalid_token") from exc


def new_refresh_token() -> tuple[str, bytes]:
    """(token for the client, SHA-256 digest for the database)."""
    token = secrets.token_urlsafe(32)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
