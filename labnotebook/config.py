"""Settings from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    pubchem_url: str
    pubchem_timeout: float
    lab_name: str
    author: str
    # Accounts. COOKIE_SECURE: "auto" (Secure cookies when the request came over HTTPS, e.g. through Cloudflare),
    # "true" or "false". ADMIN_USERNAME / ADMIN_PASSWORD create the first admin on start if there is no account yet.
    cookie_secure: str = "auto"
    session_days: int = 30
    admin_username: str = ""
    admin_password: str = ""
    # Header with the real client address set by a trusted proxy (e.g. CF-Connecting-IP behind Cloudflare Tunnel);
    # used for sign-in throttling and the activity log. Empty: the address of the connection.
    client_ip_header: str = ""
    # Where "Report a problem" in the app sends people (empty: no link)
    issues_url: str = "https://github.com/mcaragon/lab-notebook/issues/new/choose"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "notebook.sqlite"


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(os.environ.get("NOTEBOOK_DATA_DIR", "/data")),
        pubchem_url=os.environ.get("PUBCHEM_URL", "http://localhost:55055").rstrip("/"),
        pubchem_timeout=float(os.environ.get("PUBCHEM_TIMEOUT", "8")),
        lab_name=os.environ.get("LAB_NAME", ""),
        author=os.environ.get("AUTHOR_NAME", ""),
        cookie_secure=os.environ.get("COOKIE_SECURE", "auto").strip().lower(),
        session_days=int(os.environ.get("SESSION_DAYS", "30")),
        admin_username=os.environ.get("ADMIN_USERNAME", "").strip(),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        client_ip_header=os.environ.get("CLIENT_IP_HEADER", "").strip(),
        issues_url=os.environ.get("ISSUES_URL", "https://github.com/mcaragon/lab-notebook/issues/new/choose").strip(),
    )
