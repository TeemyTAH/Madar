from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.app.core.security import get_current_user, require_roles
from backend.app.schemas.auth import BootstrapAdminRequest, LoginRequest, UserCreate
from backend.app.services.auth_service import AuthConflictError, AuthInvalidCredentials, AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _service(request: Request) -> AuthService:
    manager = getattr(request.app.state, "db_manager", None)
    secret = getattr(request.app.state, "auth_secret", None)
    if manager is None or secret is None:
        raise HTTPException(status_code=503, detail="Authentication service is not initialized")
    return AuthService(manager, secret)


@router.post("/bootstrap-admin", status_code=status.HTTP_201_CREATED)
def bootstrap_admin(payload: BootstrapAdminRequest, request: Request):
    """Create the first administrator once, before any user account exists."""
    try:
        return _service(request).bootstrap_admin(
            username=payload.username,
            full_name=payload.full_name,
            password=payload.password,
        )
    except AuthConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Administrator username already exists") from exc


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    try:
        return _service(request).login(username=payload.username, password=payload.password)
    except AuthInvalidCredentials as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "user_id": int(user["UserId"]),
        "username": user["Username"],
        "full_name": user["FullName"],
        "role_name": user["RoleName"],
        "is_active": bool(user["IsActive"]),
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    actor: dict = Depends(require_roles("Admin")),
):
    try:
        return _service(request).create_user(
            username=payload.username,
            full_name=payload.full_name,
            password=payload.password,
            role_name=payload.role_name,
            actor_user_id=int(actor["UserId"]),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Username already exists") from exc
