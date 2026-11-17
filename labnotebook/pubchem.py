"""Client for the PubChem Local REST API.

All calls go through the notebook's backend, so the browser never needs to reach PubChem Local directly (the
configured URL may only be valid inside the Docker network). When PubChem Local is unreachable, methods raise
:class:`PubChemUnavailable`; callers turn that into a soft error so manual entry keeps working.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

import httpx


class PubChemUnavailable(Exception):
    pass


# Lab summary field -> reagent column
FIELD_MAP = {
    "name": "name",
    "iupac_name": "iupac_name",
    "cas": "cas",
    "molecular_formula": "formula",
    "smiles": "smiles",
    "molecular_weight": "mw",
    "density_g_cm3": "density",
    "boiling_point_c": "bp",
    "melting_point_c": "mp",
    "flash_point_c": "flash_point",
    "refractive_index": "refractive_index",
    "signal_word": "signal_word",
    "pictograms": "pictograms",
    "hazard_statements": "hazard_statements",
}
# Reagent column -> key in physical_properties of /api/compound/{cid}
PROPERTY_KEYS = {"bp": "boiling_point", "mp": "melting_point", "density": "density", "flash_point": "flash_point",
                 "refractive_index": "refractive_index"}


def summary_to_reagent(summary: dict) -> dict:
    """Map a PubChem Local lab summary to reagent columns, recording the source of each filled value."""
    out: dict[str, Any] = {"cid": summary.get("cid"), "pubchem_url": summary.get("pubchem_url")}
    sources = {}
    for src, dst in FIELD_MAP.items():
        v = summary.get(src)
        out[dst] = v
        if v not in (None, [], ""):
            sources[dst] = "pubchem"
    out["sources"] = sources
    return out


class PubChemClient:
    def __init__(self, base_url: str, timeout: float = 8.0, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)
        self._cache: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: Optional[dict] = None) -> httpx.Response:
        if not self.base_url:
            raise PubChemUnavailable("PUBCHEM_URL is not set")
        try:
            return self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise PubChemUnavailable(f"PubChem Local is not reachable at {self.base_url}: {e}") from e

    def _json(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        r = self._get(path, params)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise PubChemUnavailable(f"PubChem Local returned HTTP {r.status_code} for {path}")
        try:
            return r.json()
        except ValueError as e:
            raise PubChemUnavailable(f"PubChem Local returned invalid JSON for {path}") from e

    def health(self) -> dict:
        return self._json("/api/health") or {}

    def autocomplete(self, q: str, limit: int = 10) -> list[dict]:
        data = self._json("/api/autocomplete", {"q": q, "limit": limit}) or {}
        return data.get("suggestions", [])

    def lookup(self, q: str) -> Optional[dict]:
        return self._json("/api/lookup", {"q": q})

    def lab(self, cid: int) -> Optional[dict]:
        return self._json(f"/api/compound/{int(cid)}/lab")

    def compound(self, cid: int) -> Optional[dict]:
        return self._json(f"/api/compound/{int(cid)}")

    def property_sources(self, cid: int) -> dict:
        """Source values of the physical properties, keyed by reagent column."""
        rec = self.compound(cid) or {}
        props = rec.get("physical_properties") or {}
        return {col: props[key] for col, key in PROPERTY_KEYS.items() if props.get(key)}

    def safety_summary(self, cid: int) -> Optional[dict]:
        return self._json(f"/api/compound/{int(cid)}/safety-summary")

    def _binary(self, path: str, params: Optional[dict] = None) -> Optional[tuple[bytes, str]]:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        r = self._get(path, params)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise PubChemUnavailable(f"PubChem Local returned HTTP {r.status_code} for {path}")
        item = (r.content, r.headers.get("content-type", "image/svg+xml"))
        with self._lock:
            if len(self._cache) > 2000:
                self._cache.clear()
            self._cache[key] = item
        return item

    def structure_svg(self, cid: int, width: int = 300, height: int = 240, theme: str = "light"):
        return self._binary(f"/api/compound/{int(cid)}/structure.svg",
                            {"width": int(width), "height": int(height), "theme": theme})

    def depict_svg(self, smiles: str, width: int = 300, height: int = 240, theme: str = "light"):
        """Structure from a SMILES string, if this PubChem Local has a ``/api/depict`` endpoint (None otherwise)."""
        return self._binary("/api/depict", {"smiles": smiles, "width": int(width), "height": int(height),
                                            "theme": theme})

    def ghs_svg(self, code: str):
        return self._binary(f"/static/ghs/{code}.svg")
