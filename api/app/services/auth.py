from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.admin import Admin
from app.security import create_admin_token, hash_password, verify_password


async def get_admin_by_email(session: AsyncSession, email: str) -> Admin | None:
    stmt = select(Admin).where(func.lower(Admin.email) == email.strip().lower())
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_admin_by_id(session: AsyncSession, admin_id: uuid.UUID) -> Admin | None:
    return await session.get(Admin, admin_id)


async def authenticate(
    session: AsyncSession, settings: Settings, email: str, password: str
) -> tuple[Admin, str] | None:
    """Return (admin, jwt) on success; None for unknown email, bad password, or inactive admin.

    The password is always verified (against a dummy hash when the email is
    unknown) so the three failure modes take the same time.
    """
    admin = await get_admin_by_email(session, email)
    ok = verify_password(admin.password_hash if admin else None, password)
    if admin is None or not ok or not admin.is_active:
        return None
    admin.last_login_at = datetime.now(UTC)
    await session.commit()
    return admin, create_admin_token(settings, admin.id)


async def create_admin(session: AsyncSession, *, email: str, name: str, password: str) -> Admin:
    admin = Admin(email=email.strip(), name=name.strip(), password_hash=hash_password(password))
    session.add(admin)
    await session.commit()
    return admin


async def set_password(session: AsyncSession, admin: Admin, password: str) -> None:
    admin.password_hash = hash_password(password)
    await session.commit()


async def deactivate(session: AsyncSession, admin: Admin) -> None:
    admin.is_active = False
    await session.commit()
