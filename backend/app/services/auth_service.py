from __future__ import annotations

from typing import Any

from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.database.database_manager import DatabaseManager


class AuthServiceError(RuntimeError):
    pass


class AuthConflictError(AuthServiceError):
    pass

class AuthInvalidCredentials(AuthServiceError):
    pass


class AuthService:
    def __init__(self, manager: DatabaseManager, signing_secret: bytes) -> None:
        self.manager = manager
        self.signing_secret = signing_secret

    @staticmethod
    def _public_user(row: Any) -> dict[str, Any]:
        return {
            "user_id": int(row["UserId"]),
            "username": str(row["Username"]),
            "full_name": str(row["FullName"]),
            "role_name": str(row["RoleName"]),
            "is_active": bool(row["IsActive"]),
        }

    def _token_response(self, row: Any) -> dict[str, Any]:
        return {
            "access_token": create_access_token(int(row["UserId"]), self.signing_secret),
            "token_type": "bearer",
            "expires_in": 8 * 60 * 60,
            "user": self._public_user(row),
        }

    def bootstrap_admin(self, *, username: str, full_name: str, password: str) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = int(conn.execute("SELECT COUNT(*) FROM Users WHERE RoleName='Admin'").fetchone()[0])
            if count:
                raise AuthConflictError("An administrator account already exists; bootstrap is disabled")
            cursor = conn.execute(
                "INSERT INTO Users (Username, FullName, PasswordHash, RoleName) VALUES (?, ?, ?, 'Admin')",
                (username.strip(), full_name.strip(), hash_password(password)),
            )
            user_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO AuditLogs (EntityName, EntityId, ActionType, Details) VALUES ('Users', ?, 'BOOTSTRAP_ADMIN_CREATED', 'Initial administrator account created')",
                (str(user_id),),
            )
            row = conn.execute(
                "SELECT UserId, Username, FullName, RoleName, IsActive FROM Users WHERE UserId=?",
                (user_id,),
            ).fetchone()
        return self._token_response(row)

    def login(self, *, username: str, password: str) -> dict[str, Any]:
        with self.manager.connection() as conn:
            row = conn.execute(
                "SELECT UserId, Username, FullName, PasswordHash, RoleName, IsActive FROM Users WHERE Username=? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
            if row is None or int(row["IsActive"]) != 1 or not verify_password(password, str(row["PasswordHash"])):
                raise AuthInvalidCredentials("Invalid username or password")
            conn.execute("UPDATE Users SET LastLoginAt=CURRENT_TIMESTAMP WHERE UserId=?", (row["UserId"],))
            fresh = conn.execute(
                "SELECT UserId, Username, FullName, RoleName, IsActive FROM Users WHERE UserId=?",
                (row["UserId"],),
            ).fetchone()
        return self._token_response(fresh)

    def create_user(
        self,
        *,
        username: str,
        full_name: str,
        password: str,
        role_name: str,
        actor_user_id: int,
    ) -> dict[str, Any]:
        with self.manager.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "INSERT INTO Users (Username, FullName, PasswordHash, RoleName) VALUES (?, ?, ?, ?)",
                (username.strip(), full_name.strip(), hash_password(password), role_name),
            )
            user_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO AuditLogs (PerformedByUserId, EntityName, EntityId, ActionType, Details) VALUES (?, 'Users', ?, 'USER_CREATED', ?)",
                (actor_user_id, str(user_id), f"Created user with role {role_name}"),
            )
            row = conn.execute(
                "SELECT UserId, Username, FullName, RoleName, IsActive FROM Users WHERE UserId=?",
                (user_id,),
            ).fetchone()
        return self._public_user(row)
