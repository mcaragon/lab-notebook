"""Command line entry point.

``lab-notebook [serve] [--host HOST] [--port PORT]`` runs the server; ``lab-notebook set-password USER`` sets a new
password for an account (e.g. a forgotten admin password: ``docker exec -it lab-notebook /entrypoint.sh set-password
USER``) and signs it out everywhere.
"""
from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="lab-notebook", description="Organic chemistry lab notebook")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="Run the web server (default)")
    pw = sub.add_parser("set-password", help="Set a new password for an account")
    pw.add_argument("username")
    for parser in (p, s):
        parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
        parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = p.parse_args(argv)
    if args.cmd == "set-password":
        set_password(args.username)
        return

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


def set_password(username: str) -> None:
    import getpass
    import sys

    from . import auth, db
    from .config import load_settings

    accounts = auth.Auth(db.Store(load_settings().db_path))
    user = accounts.find_user(username)
    if not user:
        sys.exit(f"No account named {username!r}.")
    new = getpass.getpass(f"New password for {user['username']}: ")
    if getpass.getpass("Repeat it: ") != new:
        sys.exit("The passwords do not match.")
    try:
        accounts.set_password(user["id"], new)
    except auth.AuthError as e:
        sys.exit(str(e))
    accounts.update_user(user["id"], {"active": True})
    accounts.end_sessions(user["id"])
    print(f"Password set for {user['username']}; the account is active and signed out everywhere.")


if __name__ == "__main__":
    main()
