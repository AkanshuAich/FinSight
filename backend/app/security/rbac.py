"""Role-based access. The demo takes the user and role from headers; production would use SSO claims."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

ROLES = {"analyst", "senior", "auditor", "admin"}
CAN = {
    "upload": {"analyst", "senior", "admin"},
    "override": {"analyst", "senior", "admin"},
    "reveal": {"analyst", "senior", "admin"},
    "create_case": {"analyst", "senior", "admin"},
    "view_audit": {"senior", "auditor", "admin"},
    "promote_global": {"senior", "admin"},
}


@dataclass
class User:
    name: str
    role: str


def current_user(x_user: str = Header(default="analyst.demo"), x_role: str = Header(default="analyst")) -> User:
    role = x_role.lower()
    if role not in ROLES:
        raise HTTPException(400, f"unknown role {x_role!r}")
    return User(x_user, role)


def require(user: User, action: str) -> None:
    if user.role not in CAN[action]:
        raise HTTPException(403, f"role '{user.role}' cannot {action.replace('_', ' ')}")
