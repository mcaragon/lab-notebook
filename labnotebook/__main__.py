"""Command line entry point: ``lab-notebook [serve] [--host HOST] [--port PORT]``."""
from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="lab-notebook", description="Organic chemistry lab notebook")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="Run the web server (default)")
    for parser in (p, s):
        parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
        parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = p.parse_args(argv)

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
