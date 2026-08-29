"""
Who is asking, and what they are allowed to do.

Two things are being protected here, and only one of them is the data. The other
is the audit trail: an override recorded against "nurse.demo" is not evidence of
anything. Every clinical write now carries the identity of a person who
authenticated, taken from a signed token rather than from a query parameter the
caller chose for themselves.

Roles follow the PRD's five: nurse, charge nurse, clinician, ops, admin — plus
`auditor`, read-only on the trail and nothing else, because the person checking
the chain should not be able to add to it.

Passwords are salted PBKDF2-SHA256. The seeded accounts below exist so the demo
runs out of the box; a real deployment sets ATRIA_USERS and turns them off.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

ALGORITHM = "HS256"
TOKEN_MINUTES = int(os.environ.get("ATRIA_TOKEN_MINUTES", "720"))  # a long shift
_PBKDF2_ROUNDS = 240_000

#: A demo secret is generated per process if none is set, so a forgotten
#: environment variable cannot silently ship a publicly known signing key.
SECRET = os.environ.get("ATRIA_SECRET") or secrets.token_urlsafe(48)

# --- permissions -------------------------------------------------------------

#: What each role may do. Named capabilities rather than route lists, so a new
#: endpoint has to state which permission it needs instead of inheriting access.
PERMISSIONS: dict[str, set[str]] = {
    "nurse":        {"queue:read", "assess:write", "worsening:write"},
    "charge_nurse": {"queue:read", "assess:write", "worsening:write",
                     "acknowledge:write", "ops:read", "history:read"},
    "clinician":    {"queue:read", "assess:write", "worsening:write",
                     "override:write", "history:read"},
    "ops":          {"queue:read", "ops:read", "ops:write"},
    "auditor":      {"history:read"},
    "admin":        {"queue:read", "assess:write", "worsening:write",
                     "acknowledge:write", "override:write", "ops:read",
                     "ops:write", "history:read", "admin:write"},
}

#: Lowering a patient's urgency is a clinical act. Ops and auditors have no
#: business doing it however much of the board they can see.
CLINICAL_ROLES = ("nurse", "charge_nurse", "clinician", "admin")


class Principal:
    """The authenticated caller, as the rest of the service sees them."""

    def __init__(self, username: str, role: str, display: str = ""):
        self.username = username
        self.role = role
        self.display = display or username

    def can(self, permission: str) -> bool:
        return permission in PERMISSIONS.get(self.role, set())

    def as_dict(self) -> dict[str, Any]:
        return {"username": self.username, "role": self.role,
                "display": self.display,
                "permissions": sorted(PERMISSIONS.get(self.role, set()))}


# --- passwords ---------------------------------------------------------------

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                             _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(),
                                 int(rounds))
    except (ValueError, TypeError):
        return False
    # Constant-time: a timing difference here leaks the digest a byte at a time.
    return hmac.compare_digest(dk.hex(), digest)


# --- the user directory ------------------------------------------------------

#: Demo accounts. Every password is the username, which is fine for a prototype
#: nobody has real data in and unacceptable anywhere else — hence the warning
#: printed at startup.
DEMO_USERS = [
    ("nurse.demo",   "nurse",        "A. Rahman, RN"),
    ("charge.demo",  "charge_nurse", "S. Iyer, Charge Nurse"),
    ("doc.demo",     "clinician",    "Dr M. Okafor"),
    ("ops.demo",     "ops",          "Flow Coordinator"),
    ("audit.demo",   "auditor",      "Clinical Governance"),
    ("admin.demo",   "admin",        "System Administrator"),
]


def _load_users() -> dict[str, dict[str, str]]:
    """
    ATRIA_USERS, if set, is JSON: {"user": {"role": ..., "password_hash": ...}}.

    Note it takes *hashes*, never passwords. An environment variable holding a
    plaintext password ends up in a process listing and a deploy log.
    """
    raw = os.environ.get("ATRIA_USERS")
    if raw:
        return json.loads(raw)
    return {u: {"role": r, "display": d, "password_hash": hash_password(u)}
            for u, r, d in DEMO_USERS}


USERS = _load_users()
DEMO_MODE = "ATRIA_USERS" not in os.environ


def authenticate(username: str, password: str) -> Principal | None:
    rec = USERS.get(username)
    if rec is None:
        # Hash anyway, so an unknown username does not answer faster than a
        # known one with a wrong password.
        verify_password(password, hash_password("no-such-user"))
        return None
    if not verify_password(password, rec["password_hash"]):
        return None
    return Principal(username, rec["role"], rec.get("display", ""))


# --- tokens ------------------------------------------------------------------

def issue_token(p: Principal) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = {"sub": p.username, "role": p.role, "name": p.display,
               "iat": now, "exp": now + timedelta(minutes=TOKEN_MINUTES),
               "jti": secrets.token_urlsafe(8)}
    return {"access_token": jwt.encode(payload, SECRET, algorithm=ALGORITHM),
            "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60,
            "user": p.as_dict()}


oauth2 = OAuth2PasswordBearer(tokenUrl="/v1/auth/token", auto_error=False)

#: Set ATRIA_AUTH=off to run the board without logging in — useful for a demo
#: on a projector, never for anything with data in it.
AUTH_ENABLED = os.environ.get("ATRIA_AUTH", "on").lower() not in ("off", "0", "false")

ANONYMOUS = Principal("demo.open", "admin", "Demo (auth disabled)")


async def current_user(token: str | None = Depends(oauth2)) -> Principal:
    if not AUTH_ENABLED:
        return ANONYMOUS
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sign in required",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired",
                            headers={"WWW-Authenticate": "Bearer"})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token",
                            headers={"WWW-Authenticate": "Bearer"})
    return Principal(claims["sub"], claims.get("role", ""), claims.get("name", ""))


def requires(permission: str):
    """Dependency factory. `Depends(requires("override:write"))`."""

    async def guard(user: Principal = Depends(current_user)) -> Principal:
        if not user.can(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{user.role}' cannot {permission}")
        return user

    return guard


def startup_notice() -> str:
    if not AUTH_ENABLED:
        return "ATRIA: authentication DISABLED (ATRIA_AUTH=off). Demo only."
    if DEMO_MODE:
        return ("ATRIA: auth on with seeded demo accounts "
                f"({', '.join(u for u, _, _ in DEMO_USERS)}); password = username. "
                "Set ATRIA_USERS before deploying anywhere real.")
    return f"ATRIA: auth on, {len(USERS)} accounts from ATRIA_USERS."
