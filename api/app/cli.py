"""Operator CLI. These commands are never exposed over HTTP (CLAUDE.md rule 11).

    uv run python -m app.cli create-admin --email ops@example.com --name "Ops"
    uv run python -m app.cli reset-admin-password --email ops@example.com
    uv run python -m app.cli deactivate-admin --email ops@example.com

Passwords are read interactively, never from flags or environment variables,
and stored only as argon2id hashes.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.services import auth


class CliError(Exception):
    pass


def read_new_password(settings: Settings, prompt: str = "Password: ") -> str:
    password = getpass.getpass(prompt)
    if len(password) < settings.admin_password_min_length:
        raise CliError(f"password must be at least {settings.admin_password_min_length} characters")
    if getpass.getpass("Repeat password: ") != password:
        raise CliError("passwords do not match")
    return password


async def _create_admin(settings: Settings, email: str, name: str) -> str:
    password = read_new_password(settings)
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            if await auth.get_admin_by_email(session, email) is not None:
                raise CliError(f"an admin with email {email} already exists")
            admin = await auth.create_admin(session, email=email, name=name, password=password)
            return f"created admin {admin.id} ({admin.email})"
    finally:
        await engine.dispose()


async def _reset_password(settings: Settings, email: str) -> str:
    password = read_new_password(settings, "New password: ")
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            admin = await auth.get_admin_by_email(session, email)
            if admin is None:
                raise CliError(f"no admin with email {email}")
            await auth.set_password(session, admin, password)
            return f"password reset for {admin.email}"
    finally:
        await engine.dispose()


async def _deactivate(settings: Settings, email: str) -> str:
    engine = make_engine(settings.database_url)
    try:
        async with make_session_factory(engine)() as session:
            admin = await auth.get_admin_by_email(session, email)
            if admin is None:
                raise CliError(f"no admin with email {email}")
            await auth.deactivate(session, admin)
            return f"deactivated {admin.email}; existing sessions end at token expiry"
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="create an admin (password prompted)")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)

    reset = sub.add_parser("reset-admin-password", help="set a new password (prompted)")
    reset.add_argument("--email", required=True)

    deactivate = sub.add_parser("deactivate-admin", help="block further logins")
    deactivate.add_argument("--email", required=True)
    return parser


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    try:
        if args.command == "create-admin":
            message = asyncio.run(_create_admin(settings, args.email, args.name))
        elif args.command == "reset-admin-password":
            message = asyncio.run(_reset_password(settings, args.email))
        else:
            message = asyncio.run(_deactivate(settings, args.email))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
