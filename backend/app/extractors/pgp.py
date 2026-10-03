"""
Minimal OpenPGP public-key-block parser (RFC 4880).

Dark web vendors routinely paste their full PGP public key. The key's
User ID packets carry a name and email the operator chose — often the
single biggest de-anonymizing leak on a page. This module extracts
those User IDs and the key's real fingerprint, without any third-party
dependency and without doing any cryptography beyond the SHA-1 that
defines a v4 fingerprint.

It only reads data. It never verifies signatures or decrypts anything.
"""

import base64
import hashlib
import re


ARMOR_RE = re.compile(
    r"-----BEGIN PGP PUBLIC KEY BLOCK-----"
    r"(.*?)"
    r"-----END PGP PUBLIC KEY BLOCK-----",
    re.DOTALL,
)

UID_RE = re.compile(r"^\s*(?P<name>[^(<]*?)\s*(?:\((?P<comment>[^)]*)\))?\s*"
                    r"(?:<(?P<email>[^>]+)>)?\s*$")


def find_key_blocks(text: str) -> list[dict]:
    """
    Return parsed public keys found in `text`.

    Each item: {fingerprint, key_id, uids: [{raw, name, email}]}.
    Malformed blocks are skipped rather than raising.
    """

    keys = []

    for match in ARMOR_RE.finditer(text):

        data = _dearmor(match.group(1))

        if data is None:
            continue

        key = _parse_packets(data)

        if key and (key["fingerprint"] or key["uids"]):
            keys.append(key)

    return keys


def _dearmor(block: str) -> bytes | None:
    """Strip armor headers/CRC and base64-decode the body."""

    lines = block.strip().splitlines()

    body = []
    seen_blank = False

    for line in lines:
        stripped = line.strip()

        # Armor headers (Version:, Comment:) end at the first blank line.
        if not seen_blank:
            if not stripped:
                seen_blank = True
            elif ":" in stripped and " " not in stripped.split(":", 1)[0]:
                continue
            else:
                # No armor headers at all; this line is already base64.
                seen_blank = True
                body.append(stripped)
            continue

        # The CRC-24 checksum line starts with '='.
        if stripped.startswith("="):
            continue

        body.append(stripped)

    try:
        return base64.b64decode("".join(body), validate=False)
    except (ValueError, base64.binascii.Error):
        return None


def _parse_packets(data: bytes) -> dict | None:
    """Walk the packet stream, collecting the primary key and UIDs."""

    fingerprint = None
    key_id = None
    uids: list[dict] = []

    i = 0
    n = len(data)

    while i < n:

        tag, body, i = _read_packet(data, i)

        if tag is None:
            break

        # Public-Key (6) or Public-Subkey (14).
        if tag in (6, 14) and fingerprint is None:
            fp = _v4_fingerprint(body)
            if fp:
                fingerprint = fp
                key_id = fp[-16:]

        # User ID (13).
        elif tag == 13:
            uids.append(_parse_uid(body))

    return {
        "fingerprint": fingerprint,
        "key_id": key_id,
        "uids": uids,
    }


def _read_packet(data: bytes, i: int) -> tuple[int | None, bytes, int]:
    """Read one packet header + body. Returns (tag, body, next_index)."""

    if i >= len(data):
        return None, b"", i

    first = data[i]

    # Every packet header has bit 7 set.
    if not first & 0x80:
        return None, b"", len(data)

    i += 1

    if first & 0x40:
        # New-format header.
        tag = first & 0x3F
        length, i = _new_length(data, i)
    else:
        # Old-format header.
        tag = (first & 0x3C) >> 2
        length_type = first & 0x03

        if length_type == 0:
            length = data[i]; i += 1
        elif length_type == 1:
            length = int.from_bytes(data[i:i + 2], "big"); i += 2
        elif length_type == 2:
            length = int.from_bytes(data[i:i + 4], "big"); i += 4
        else:
            # Indeterminate length: take the rest of the stream.
            length = len(data) - i

    if length is None or length < 0:
        return None, b"", len(data)

    body = data[i:i + length]

    return tag, body, i + length


def _new_length(data: bytes, i: int) -> tuple[int | None, int]:
    if i >= len(data):
        return None, i

    first = data[i]; i += 1

    if first < 192:
        return first, i

    if first < 224:
        if i >= len(data):
            return None, i
        second = data[i]; i += 1
        return ((first - 192) << 8) + second + 192, i

    if first == 255:
        length = int.from_bytes(data[i:i + 4], "big"); i += 4
        return length, i

    # Partial body lengths are not used by key or UID packets; stop.
    return None, i


def _v4_fingerprint(body: bytes) -> str | None:
    """A v4 fingerprint is SHA-1 of 0x99 || len || public-key packet body."""

    if not body or body[0] != 4:
        return None

    prefix = b"\x99" + len(body).to_bytes(2, "big") + body

    return hashlib.sha1(prefix).hexdigest().upper()


def _parse_uid(body: bytes) -> dict:
    raw = body.decode("utf-8", errors="replace").strip()

    match = UID_RE.match(raw)

    name = (match.group("name") or "").strip() if match else ""
    email = (match.group("email") or "").strip() if match else ""

    return {"raw": raw, "name": name, "email": email}
