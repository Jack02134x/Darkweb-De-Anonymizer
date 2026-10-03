"""
Verify a PGP fingerprint against a public keyserver.

A fingerprint extracted from a page is only a claim until a key with
that fingerprint is shown to exist. keys.openpgp.org answers that: a
hit confirms the key is real and may return its User IDs (name/email)
— a direct identity lead. A miss means the 40-hex string was almost
certainly not a key (often a SHA-1 file hash).

This talks to the clearnet keyserver, not Tor.
"""

import logging
import re

import httpx

from ..config import settings
from ..extractors.pgp import find_key_blocks


log = logging.getLogger("tracepoint.pgpverify")

KEYSERVER = "https://keys.openpgp.org"

_FPR_RE = re.compile(r"[0-9A-Fa-f]{40}")


def normalize_fingerprint(value: str) -> str | None:
    cleaned = re.sub(r"\s+|^0x", "", value.strip(), flags=re.IGNORECASE).upper()

    return cleaned if _FPR_RE.fullmatch(cleaned) else None


async def verify_fingerprint(fingerprint: str) -> dict:
    """
    Look a fingerprint up on keys.openpgp.org.

    Returns {fingerprint, exists, keyserver, uids, key_url, error}.
    `uids` is populated when the keyserver serves identity info.
    """

    fpr = normalize_fingerprint(fingerprint)

    if not fpr:
        return {
            "fingerprint": fingerprint,
            "exists": False,
            "error": "Not a valid 40-hex PGP fingerprint.",
        }

    url = f"{KEYSERVER}/vks/v1/by-fingerprint/{fpr}"

    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        ) as client:
            response = await client.get(url)

    except httpx.HTTPError as exc:
        return {
            "fingerprint": fpr,
            "exists": False,
            "keyserver": KEYSERVER,
            "error": f"Keyserver unreachable: {exc}",
        }

    if response.status_code == 404:
        return {
            "fingerprint": fpr,
            "exists": False,
            "keyserver": KEYSERVER,
            "uids": [],
        }

    if response.status_code != 200:
        return {
            "fingerprint": fpr,
            "exists": False,
            "keyserver": KEYSERVER,
            "error": f"Keyserver returned HTTP {response.status_code}.",
        }

    # The keyserver returns the armored key. Parse its UIDs when present
    # (identity info is only served for verified addresses).
    uids = []

    for key in find_key_blocks(response.text):
        for uid in key["uids"]:
            if uid["name"] or uid["email"]:
                uids.append(uid)

    log.info("Verified %s on keyserver: %d UID(s)", fpr, len(uids))

    return {
        "fingerprint": fpr,
        "exists": True,
        "keyserver": KEYSERVER,
        "uids": uids,
        "key_url": url,
    }
