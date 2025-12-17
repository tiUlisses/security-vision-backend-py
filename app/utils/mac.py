"""MAC address utilities.

We normalize MACs to a canonical *12-hex uppercase* form whenever possible.
This makes it easier to match payloads coming as:

- "AC233FC12E2B"
- "AC:23:3F:C1:2E:2B"
- "ac-23-3f-c1-2e-2b"
"""

from __future__ import annotations

import re
from typing import Optional, Set


_NON_HEX = re.compile(r"[^0-9A-Fa-f]")


def normalize_mac(mac: str | None) -> Optional[str]:
    """Return canonical 12-hex uppercase MAC when possible."""
    if not mac:
        return None
    mac = str(mac).strip()
    if not mac:
        return None

    cleaned = _NON_HEX.sub("", mac).upper()
    if len(cleaned) == 12:
        return cleaned

    # If it isn't 12-hex, we still return an uppercase best-effort string
    # (some vendors use longer identifiers).
    return cleaned or None


def mac_to_colon(mac: str | None) -> Optional[str]:
    """Return colon-separated MAC (AA:BB:CC:DD:EE:FF) when possible."""
    norm = normalize_mac(mac)
    if not norm:
        return None
    if len(norm) != 12:
        return norm
    return ":".join(norm[i : i + 2] for i in range(0, 12, 2))


def candidate_macs(mac: str | None) -> Set[str]:
    """Return a set of likely DB representations for a MAC.

This lets us match databases that store MACs with or without separators.
"""
    cands: Set[str] = set()
    if not mac:
        return cands

    raw = str(mac).strip()
    if raw:
        cands.add(raw)
        cands.add(raw.upper())

    norm = normalize_mac(raw)
    if norm:
        cands.add(norm)
        col = mac_to_colon(norm)
        if col:
            cands.add(col)
            cands.add(col.upper())

    return cands
