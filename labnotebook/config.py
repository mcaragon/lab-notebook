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
    )
