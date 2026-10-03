import hashlib
import re

from ..models import Entity, EntityType
from .pgp import ARMOR_RE, find_key_blocks


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
    r"(?![\w.-])"
)

IPV4_RE = re.compile(
    r"(?<![\w.])"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
    r"(?:\."
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}"
    r"(?![\w.])"
)

# Require a plausible TLD. This prevents things like "B.Tech"
# from being classified as a domain.
DOMAIN_RE = re.compile(
    r"(?<![@\w.-])"
    r"(?:"
    r"[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"\."
    r")+"
    r"[A-Za-z]{2,63}"
    r"(?![\w.-])"
)

BTC_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:"
    r"1[a-km-zA-HJ-NP-Z1-9]{25,34}"
    r"|"
    r"3[a-km-zA-HJ-NP-Z1-9]{25,34}"
    r"|"
    r"bc1[a-zA-HJ-NP-Z0-9]{39,59}"
    r")"
    r"(?![A-Za-z0-9])"
)

# A bare 40-hex string is NOT a PGP fingerprint — it also matches every
# SHA-1 hash (imageboards name uploaded files by hash, so pages are full
# of them). A fingerprint is only accepted when it carries PGP context or
# the distinctive spaced-group layout. Real pasted keys are parsed
# separately and authoritatively by extractors/pgp.py.
PGP_CONTEXT_RE = re.compile(
    r"(?i)"
    r"(?:pgp|gpg|openpgp|fingerprint|fpr|key[\s-]*id)"
    r"[^0-9A-Fa-fx]{0,40}"
    r"(?:0x)?"
    r"((?:[0-9A-Fa-f]{4}\s+){9}[0-9A-Fa-f]{4}|[0-9A-Fa-f]{40})"
)

# "AAAA BBBB CCCC …" — ten space-separated groups of four hex. This layout
# is how GnuPG prints a fingerprint and essentially never occurs by chance.
PGP_SPACED_RE = re.compile(
    r"(?<![0-9A-Fa-f])"
    r"(?:[0-9A-Fa-f]{4}\s+){9}[0-9A-Fa-f]{4}"
    r"(?![0-9A-Fa-f])"
    # Not part of a longer run of groups (e.g. a leading "2024" year),
    # which would misalign the 40-hex window.
    r"(?!\s+[0-9A-Fa-f]{4})"
)

# Monero: 95-char Base58, standard addresses start '4', subaddresses '8'.
MONERO_RE = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])"
    r"[48][0-9A-B]"
    r"[1-9A-HJ-NP-Za-km-z]{93}"
    r"(?![1-9A-HJ-NP-Za-km-z])"
)

# Deliberately NOT used as a generic "@something" detector.
#
# We only accept a Telegram handle when the surrounding text gives us
# reasonable context that it is actually a Telegram username.
TELEGRAM_CONTEXT_RE = re.compile(
    r"(?i)"
    r"(?:telegram|tg|t\.me)"
    r"\s*"
    r"(?:username|handle|user|id)?"
    r"\s*[:=]?\s*"
    r"@([A-Za-z0-9_]{5,32})"
)

TME_URL_RE = re.compile(
    r"(?i)"
    r"(?:https?://)?"
    r"(?:www\.)?"
    r"t\.me/"
    r"([A-Za-z0-9_]{5,32})"
)


# ---------------------------------------------------------------------------
# Values that should never become entities
# ---------------------------------------------------------------------------

COMMON_NON_DOMAIN_WORDS = {
    "b.tech",
    "m.tech",
    "ph.d",
    "e.g",
    "i.e",
    "etc",
}

# File names look like domains to the regex (name "." extension). When the
# "TLD" is a known file extension, it is a filename, not a domain.
FILE_EXTENSIONS = {
    "html", "htm", "php", "asp", "aspx", "jsp", "cgi",
    "js", "mjs", "ts", "css", "scss", "json", "xml", "yml", "yaml",
    "png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "avif",
    "mp3", "mp4", "webm", "avi", "mov", "wav", "ogg", "flac",
    "pdf", "txt", "md", "csv", "tsv", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "rtf", "odt",
    "zip", "gz", "tar", "rar", "7z", "bz2", "xz",
    "exe", "dll", "bin", "iso", "img", "apk", "deb", "rpm",
    "py", "rb", "go", "rs", "c", "cpp", "h", "java", "sh", "class",
    "log", "cfg", "ini", "conf", "dat", "db", "sql", "bak",
}

COMMON_MENTION_WORDS = {
    "github",
    "gitlab",
    "microsoft",
    "google",
    "amazon",
    "apple",
    "meta",
    "linkedin",
    "twitter",
    "x",
    "youtube",
    "reddit",
    "wikimedia",
    "dukaan",
    "gnosispay",
    "gssoc",
    "mlh",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(
    entity_type: EntityType,
    value: str,
) -> str:

    value = value.strip()

    if entity_type in {
        EntityType.email,
        EntityType.domain,
        EntityType.telegram,
    }:
        return value.lower()

    if entity_type == EntityType.pgp_fingerprint:
        return value.upper()

    return value


def entity_id(
    entity_type: EntityType,
    normalized: str,
) -> str:

    digest = hashlib.sha256(
        f"{entity_type.value}:{normalized}".encode(
            "utf-8"
        )
    ).hexdigest()[:16]

    return f"{entity_type.value}:{digest}"


def make_entity(
    entity_type: EntityType,
    value: str,
) -> Entity:

    normalized = normalize(
        entity_type,
        value,
    )

    return Entity(
        id=entity_id(
            entity_type,
            normalized,
        ),
        type=entity_type,
        value=value,
        normalized=normalized,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add(
    found: dict[tuple[EntityType, str], Entity],
    entity: Entity,
) -> None:

    key = (
        entity.type,
        entity.normalized,
    )

    found[key] = entity


def _add_fingerprint(
    found: dict[tuple[EntityType, str], Entity],
    raw: str,
) -> None:
    """Normalize a matched fingerprint (strip spaces, upper) and store it."""

    value = re.sub(r"\s+", "", raw).upper()

    if len(value) != 40:
        return

    # Reject degenerate strings like 40 identical characters.
    if len(set(value)) <= 2:
        return

    _add(
        found,
        make_entity(EntityType.pgp_fingerprint, value),
    )


def _clean_domain(
    value: str,
) -> str | None:

    value = value.strip().lower()

    if value in COMMON_NON_DOMAIN_WORDS:
        return None

    # Onion services are not generic domains; the crawler handles them.
    if value.endswith(".onion"):
        return None

    # TLD must be alphabetic and 2+ characters.
    parts = value.split(".")

    if len(parts) < 2:
        return None

    tld = parts[-1]

    if not tld.isalpha() or len(tld) < 2:
        return None

    # A filename (foo.html, index.php) is not a domain.
    if tld in FILE_EXTENSIONS:
        return None

    return value


def _extract_telegram(
    text: str,
) -> list[str]:

    handles = []

    for match in TELEGRAM_CONTEXT_RE.finditer(text):
        handles.append(match.group(1))

    for match in TME_URL_RE.finditer(text):
        handles.append(match.group(1))

    return handles


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------

def extract_entities(
    text: str,
) -> list[Entity]:

    if not text:
        return []

    found: dict[
        tuple[EntityType, str],
        Entity,
    ] = {}

    # ---------------------------------------------------------
    # PGP public key blocks FIRST.
    #
    # The User ID inside a pasted key carries the operator's
    # chosen name and email — the strongest single leak on a
    # page. We take the real fingerprint and UID fields, then
    # blank the armored block so its base64 body does not feed
    # the generic regexes below with noise.
    # ---------------------------------------------------------

    for key in find_key_blocks(text):

        if key["fingerprint"]:
            _add(
                found,
                make_entity(
                    EntityType.pgp_fingerprint,
                    key["fingerprint"],
                ),
            )

        for uid in key["uids"]:

            if uid["email"]:
                _add(
                    found,
                    make_entity(EntityType.email, uid["email"]),
                )

            # A single-token UID name is a handle worth linking on;
            # multi-word real names are kept only as context, not
            # as a username entity.
            name = uid["name"]

            if (
                name
                and " " not in name
                and name.lower() not in COMMON_MENTION_WORDS
            ):
                _add(
                    found,
                    make_entity(EntityType.username, name),
                )

    text = ARMOR_RE.sub(
        lambda match: " " * len(match.group(0)),
        text,
    )

    # ---------------------------------------------------------
    # Find email spans FIRST.
    #
    # We need these later so that something like:
    #
    # user@example.com
    #
    # does not also produce:
    #
    # example.com
    # ---------------------------------------------------------

    email_matches = list(
        EMAIL_RE.finditer(text)
    )

    email_spans = [
        match.span()
        for match in email_matches
    ]

    # ---------------------------------------------------------
    # Emails
    # ---------------------------------------------------------

    for match in email_matches:

        value = match.group(0)

        _add(
            found,
            make_entity(
                EntityType.email,
                value,
            ),
        )

    # ---------------------------------------------------------
    # IPv4
    # ---------------------------------------------------------

    for match in IPV4_RE.finditer(text):

        value = match.group(0)

        _add(
            found,
            make_entity(
                EntityType.ipv4,
                value,
            ),
        )

    # ---------------------------------------------------------
    # Bitcoin
    # ---------------------------------------------------------

    for match in BTC_RE.finditer(text):

        value = match.group(0)

        _add(
            found,
            make_entity(
                EntityType.btc_wallet,
                value,
            ),
        )

    # ---------------------------------------------------------
    # Monero
    # ---------------------------------------------------------

    for match in MONERO_RE.finditer(text):

        value = match.group(0)

        _add(
            found,
            make_entity(
                EntityType.monero_wallet,
                value,
            ),
        )

    # ---------------------------------------------------------
    # PGP fingerprints (context-qualified only; see PGP_CONTEXT_RE)
    # ---------------------------------------------------------

    for match in PGP_CONTEXT_RE.finditer(text):
        _add_fingerprint(found, match.group(1))

    for match in PGP_SPACED_RE.finditer(text):
        _add_fingerprint(found, match.group(0))

    # ---------------------------------------------------------
    # Telegram
    # ---------------------------------------------------------

    for value in _extract_telegram(text):

        if value.lower() in COMMON_MENTION_WORDS:
            continue

        _add(
            found,
            make_entity(
                EntityType.telegram,
                f"@{value}",
            ),
        )

    # ---------------------------------------------------------
    # Domains
    # ---------------------------------------------------------

    for match in DOMAIN_RE.finditer(text):

        value = match.group(0)

        # Ignore domains that are actually part of
        # an email address.
        inside_email = any(
            start <= match.start() < end
            or start < match.end() <= end
            for start, end in email_spans
        )

        if inside_email:
            continue

        # Domains used purely as social-platform URL
        # components should not become independent
        # investigation entities.
        if value.lower() in {
            "t.me",
            "telegram.me",
        }:
            continue

        value = _clean_domain(value)

        if not value:
            continue

        _add(
            found,
            make_entity(
                EntityType.domain,
                value,
            ),
        )

    # ---------------------------------------------------------
    # Return unique entities
    # ---------------------------------------------------------

    return sorted(
        found.values(),
        key=lambda entity: (
            entity.type.value,
            entity.normalized,
        ),
    )