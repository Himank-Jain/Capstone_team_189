"""Manage dashboard accounts from the terminal.

Run from the repository root with the same environment as the API (in
particular the same CAPSTONE_DATABASE_URL), e.g.:

    python -m scripts.manage_users list
    python -m scripts.manage_users promote you@example.com            # make admin
    python -m scripts.manage_users promote you@example.com --role OPERATOR
    python -m scripts.manage_users create-admin admin@example.com     # prompts for a password
    python -m scripts.manage_users reset-password you@example.com     # prompts for a new password

"Admin" means OWNER of every demo workspace: it unlocks the Admin console,
member management, and every operator action.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

import bcrypt
from fastapi import HTTPException

from phase3.api.routers import _support
from phase3.api.routers.auth import (
    _account_rows,
    _normalize_email,
    _validate_password,
    ensure_admin_account,
    set_workspace_access,
)
from phase3.db.models import UserRow


def _prompt_password(confirm: bool = True) -> str:
    password = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Repeat password: ") != password:
        raise SystemExit("Passwords do not match.")
    return password


def _user_id_for(email: str) -> str:
    with _support.platform_session_factory.session_scope() as session:
        row = session.query(UserRow).filter_by(email=_normalize_email(email)).one_or_none()
        if row is None:
            raise SystemExit(f"No account uses {email}. Register it in the dashboard first.")
        return row.user_id


def cmd_list(_args: argparse.Namespace) -> None:
    rows = _account_rows()
    if not rows:
        print("No accounts yet. Register one in the dashboard.")
        return
    for row in rows:
        roles = ", ".join(f"{item['tenant_name']}={item['role'].lower()}" for item in row["memberships"]) or "no access"
        print(f"{row['email']:<40} {'ADMIN' if row['is_admin'] else '':<6} {roles}")


def cmd_promote(args: argparse.Namespace) -> None:
    user_id = _user_id_for(args.email)
    set_workspace_access(user_id, args.role)
    label = "an admin (owner of every workspace)" if args.role == "OWNER" else f"{args.role.lower()} in every workspace"
    print(f"{args.email} is now {label}. Sign out and back in to refresh the dashboard.")


def cmd_create_admin(args: argparse.Namespace) -> None:
    password = os.getenv(args.password_env, "") if args.password_env else ""
    with _support.platform_session_factory.session_scope() as session:
        exists = session.query(UserRow).filter_by(email=_normalize_email(args.email)).one_or_none() is not None
    if not exists and not password:
        password = _prompt_password()
    _, created = ensure_admin_account(args.email, password or None)
    print(f"{'Created' if created else 'Promoted existing account'} {args.email} as admin.")


def cmd_reset_password(args: argparse.Namespace) -> None:
    user_id = _user_id_for(args.email)
    password = _prompt_password()
    _validate_password(password)
    rounds = int(os.getenv("PLATFORM_BCRYPT_ROUNDS", "12"))
    digest = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("utf-8")
    with _support.platform_session_factory.session_scope() as session:
        session.get(UserRow, user_id).password_hash = digest
    print(f"Password updated for {args.email}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage CAPSTONE-189 dashboard accounts.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List accounts and their roles").set_defaults(func=cmd_list)
    promote = sub.add_parser("promote", help="Set an account's role in every workspace (default: admin)")
    promote.add_argument("email")
    promote.add_argument("--role", choices=["OWNER", "OPERATOR", "VIEWER"], default="OWNER")
    promote.set_defaults(func=cmd_promote)
    create = sub.add_parser("create-admin", help="Create an admin account (or promote an existing one)")
    create.add_argument("email")
    create.add_argument("--password-env", help="Read the password from this environment variable instead of prompting")
    create.set_defaults(func=cmd_create_admin)
    reset = sub.add_parser("reset-password", help="Set a new password for an account")
    reset.add_argument("email")
    reset.set_defaults(func=cmd_reset_password)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except HTTPException as exc:
        print(f"Error: {exc.detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
