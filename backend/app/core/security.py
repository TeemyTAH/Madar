from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

PASSWORD_ITERATIONS = 310_000
TOKEN_LIFETIME_SECONDS = 8 * 60 * 60
SECRET_FILENAME = ".madar_auth_secret"
bearer_scheme = HTTPBearer(auto_error=False)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def load_or_create_signing_secret(storage_dir: str | Path) -> bytes:
    directory = Path(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / SECRET_FILENAME
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(secrets.token_bytes(32))
            stream.flush()
            os.fsync(stream.fileno())
    secret = path.read_bytes()
    if len(secret) < 32:
        raise RuntimeError("Madar signing secret is missing or invalid")
    return secret


def create_access_token(
    user_id: int,
    secret: bytes,
    *,
    now: int | None = None,
    lifetime_seconds: int = TOKEN_LIFETIME_SECONDS,
) -> str:
    issued_at = int(time.time() if now is None else now)
    payload = {"sub": int(user_id), "iat": issued_at, "exp": issued_at + int(lifetime_seconds)}
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def decode_access_token(token: str, secret: bytes, *, now: int | None = None) -> int | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected_signature, _b64decode(supplied_signature)):
            return None
        payload: dict[str, Any] = json.loads(_b64decode(encoded).decode("utf-8"))
        current = int(time.time() if now is None else now)
        user_id = int(payload["sub"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
        if user_id <= 0 or issued_at > current + 60 or expires_at <= current or expires_at <= issued_at:
            return None
        return user_id
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        return None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    # HTTPBearer also publishes the Bearer security scheme in OpenAPI/Swagger.
    # The middleware performs signature verification and loads the current user.
    user = getattr(request.state, "current_user", None)
    if not credentials or credentials.scheme.lower() != "bearer" or not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_roles(*allowed_roles: str) -> Callable[..., dict[str, Any]]:
    def dependency(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user.get("RoleName") not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return user
    return dependency


def install_api_auth_middleware(app) -> None:
    """Require a valid bearer token for all versioned API routes except first-run auth."""
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def authenticate_api_request(request: Request, call_next):
        path = request.url.path
        public_paths = {
            "/api/v1/auth/bootstrap-admin",
            "/api/v1/auth/login",
        }
        normalized_path = path.rstrip("/")
        if path.startswith("/api/v1/") and normalized_path not in public_paths:
            manager = getattr(request.app.state, "db_manager", None)
            secret = getattr(request.app.state, "auth_secret", None)
            if manager is None or secret is None:
                return JSONResponse(status_code=503, content={"detail": "Authentication service is unavailable"})
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            user_id = decode_access_token(token, secret) if scheme.lower() == "bearer" and token else None
            if user_id is None:
                return JSONResponse(status_code=401, content={"detail": "A valid Bearer token is required"})
            try:
                with manager.connection() as conn:
                    row = conn.execute(
                        "SELECT UserId, Username, FullName, RoleName, IsActive FROM Users WHERE UserId=?",
                        (user_id,),
                    ).fetchone()
            except Exception:
                return JSONResponse(status_code=503, content={"detail": "Unable to verify API identity"})
            if row is None or int(row["IsActive"]) != 1:
                return JSONResponse(status_code=401, content={"detail": "User is inactive or no longer exists"})
            role = str(row["RoleName"])
            restricted_ai_path = (
                path.startswith("/api/v1/uploads/")
                or path.startswith("/api/v1/ai/")
                or path.startswith("/api/v1/grading/")
            )
            restricted_region_write = path.startswith("/api/v1/answers/") and request.method.upper() != "GET"
            if (restricted_ai_path or restricted_region_write) and role not in {"Admin", "Teacher"}:
                return JSONResponse(status_code=403, content={"detail": "Teacher or Admin role required for this operation"})
            request.state.current_user = dict(row)
        return await call_next(request)
