from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CollectorStatus(str, Enum):
    success = "success"
    empty = "empty"
    blocked = "blocked"
    error = "error"
    timeout = "timeout"
    skipped = "skipped"


class CollectorCategory(str, Enum):
    surface = "surface"
    onion = "onion"


class TargetType(str, Enum):
    username = "username"
    email = "email"
    domain = "domain"
    url = "url"
    ip = "ip"
    wallet = "wallet"
    pgp = "pgp"
    text = "text"


class EvidenceType(str, Enum):
    profile = "profile"
    webpage = "webpage"
    post = "post"
    repository = "repository"
    document = "document"
    api_result = "api_result"
    unknown = "unknown"


class SourceKind(str, Enum):
    github = "github"
    gitlab = "gitlab"
    reddit = "reddit"
    webpage = "webpage"
    wayback = "wayback"
    commoncrawl = "commoncrawl"
    search = "search"
    onion = "onion"
    synthetic = "synthetic"
    unknown = "unknown"


class EntityType(str, Enum):
    username = "username"
    email = "email"
    domain = "domain"
    url = "url"
    ipv4 = "ipv4"
    ipv6 = "ipv6"
    btc_wallet = "btc_wallet"
    monero_wallet = "monero_wallet"
    pgp_fingerprint = "pgp_fingerprint"
    telegram = "telegram"
    unknown = "unknown"


class Target(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    type: TargetType


class Entity(BaseModel):
    id: str
    type: EntityType
    value: str
    normalized: str


class Evidence(BaseModel):
    id: str

    source: str
    source_kind: SourceKind

    evidence_type: EvidenceType

    url: str | None = None
    title: str | None = None

    author: str | None = None
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utc_now)

    excerpt: str | None = None
    content: str | None = None

    entities: list[Entity] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)

    verified: bool = False


class CollectionRun(BaseModel):
    source: str
    category: CollectorCategory

    status: CollectorStatus

    query: str

    started_at: datetime = Field(
        default_factory=utc_now
    )

    completed_at: datetime | None = None

    result_count: int = 0

    error: str | None = None

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class Investigation(BaseModel):
    id: str

    target: Target

    created_at: datetime = Field(
        default_factory=utc_now
    )

    updated_at: datetime = Field(
        default_factory=utc_now
    )

    status: str = "created"

    evidence: list[Evidence] = Field(
        default_factory=list
    )

    entities: list[Entity] = Field(
        default_factory=list
    )

    collection_runs: list[CollectionRun] = Field(
        default_factory=list
    )

    errors: list[str] = Field(
        default_factory=list
    )


class InvestigationCreate(BaseModel):
    target: Target


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)

    sources: list[str] = Field(
        default_factory=lambda: [
            "github",
            "reddit",
        ]
    )

    max_results: int = Field(
        default=20,
        ge=1,
        le=100,
    )


class URLRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
