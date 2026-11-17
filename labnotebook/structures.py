"""Structure images for reagents. PubChem Local draws all of them; the notebook never renders structures itself.

* Compounds with a PubChem CID: ``/api/compound/{cid}/structure.svg``.
* Compounds entered by hand with a SMILES string: ``/api/depict?smiles=…&width=…&height=…&theme=…``, if PubChem
  Local provides that endpoint. Until it does, these compounds are shown without a structure.
"""
from __future__ import annotations

from typing import Optional

from .pubchem import PubChemClient, PubChemUnavailable

Image = tuple[bytes, str]


def structure(client: Optional[PubChemClient], cid: Optional[int], smiles: Optional[str], width: int = 300,
              height: int = 240, theme: str = "light") -> Optional[Image]:
    """Structure image from PubChem Local, by CID or else by SMILES. None if it has none or is unreachable."""
    if client is None:
        return None
    try:
        if cid:
            img = client.structure_svg(cid, width, height, theme)
            if img:
                return img
        if smiles:
            img = client.depict_svg(smiles, width, height, theme)
            if img and img[1].startswith("image/"):
                return img
    except PubChemUnavailable:
        pass
    return None
