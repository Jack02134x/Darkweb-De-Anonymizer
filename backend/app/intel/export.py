"""Export the intelligence set as CSV, JSON or a readable report."""

import csv
import io
import json

from .store import get_actor, list_actors, query_observations, stats


def _actor_rows() -> list[dict]:
    """Flattened actor records with their identifiers folded in."""

    rows = []

    for summary in list_actors(limit=10000):

        actor = get_actor(summary["handle"])

        if not actor:
            continue

        identifiers = actor["identifiers"]

        rows.append(
            {
                "handle": actor["handle"],
                "category": actor["category"] or "",
                "attribution_confidence": actor["attribution_confidence"],
                "first_seen": actor["first_seen"] or "",
                "last_seen": actor["last_seen"] or "",
                "identifier_count": len(identifiers),
                "pgp_fingerprints": _join(identifiers, "pgp_fingerprint"),
                "btc_wallets": _join(identifiers, "btc_wallet"),
                "monero_wallets": _join(identifiers, "monero_wallet"),
                "emails": _join(identifiers, "email"),
                "telegram": _join(identifiers, "telegram"),
                "linked_handles": "; ".join(
                    link["other_handle"] for link in actor["links"]
                ),
                "source_count": len(actor["sources"]),
            }
        )

    return rows


def _join(identifiers: list[dict], itype: str) -> str:
    return "; ".join(
        i["identifier_value"]
        for i in identifiers
        if i["identifier_type"] == itype
    )


def export_actors_csv() -> str:
    rows = _actor_rows()

    buffer = io.StringIO()

    fieldnames = [
        "handle",
        "category",
        "attribution_confidence",
        "first_seen",
        "last_seen",
        "identifier_count",
        "pgp_fingerprints",
        "btc_wallets",
        "monero_wallets",
        "emails",
        "telegram",
        "linked_handles",
        "source_count",
    ]

    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return buffer.getvalue()


def export_observations_csv(**filters) -> str:
    rows = query_observations(limit=100000, **filters)

    buffer = io.StringIO()

    fieldnames = [
        "observed_at",
        "actor_handle",
        "identifier_type",
        "identifier_value",
        "host",
        "source_url",
        "title",
    ]

    writer = csv.DictWriter(
        buffer,
        fieldnames=fieldnames,
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)

    return buffer.getvalue()


def export_json(**filters) -> str:
    actors = [
        get_actor(a["handle"])
        for a in list_actors(limit=10000)
    ]

    payload = {
        "generated_at": _now(),
        "summary": stats(),
        "actors": [a for a in actors if a],
        "observations": query_observations(limit=100000, **filters),
    }

    return json.dumps(payload, indent=2, default=str)


def export_report_html() -> str:
    """A self-contained HTML report suitable for printing to PDF."""

    summary = stats()
    actors = [get_actor(a["handle"]) for a in list_actors(limit=500)]
    actors = [a for a in actors if a]

    cards = []

    for actor in actors:

        ident_rows = "".join(
            f"<tr><td>{_esc(i['identifier_type'])}</td>"
            f"<td class='mono'>{_esc(i['identifier_value'])}</td></tr>"
            for i in actor["identifiers"]
        ) or "<tr><td colspan='2' class='muted'>None recorded</td></tr>"

        links = "".join(
            f"<li>{_esc(l['other_handle'])} "
            f"<span class='muted'>({_esc(l['link_type'])}, "
            f"confidence {l['confidence']:.2f})</span></li>"
            for l in actor["links"]
        ) or "<li class='muted'>No cross-actor links</li>"

        confidence = actor["attribution_confidence"]

        cards.append(f"""
        <section class="actor">
          <h2>{_esc(actor['handle'])}
            <span class="conf">attribution {confidence:.0%}</span>
          </h2>
          <p class="meta">
            Category: {_esc(actor['category'] or 'uncategorized')} ·
            First seen: {_esc(actor['first_seen'] or '—')} ·
            Last seen: {_esc(actor['last_seen'] or '—')} ·
            Sources: {len(actor['sources'])}
          </p>
          <table>
            <thead><tr><th>Identifier type</th><th>Value</th></tr></thead>
            <tbody>{ident_rows}</tbody>
          </table>
          <h3>Linked personas</h3>
          <ul>{links}</ul>
        </section>
        """)

    by_type = "".join(
        f"<li><b>{v}</b> {_esc(k)}</li>"
        for k, v in summary["identifiers_by_type"].items()
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TracePoint — Threat Actor Intelligence Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 900px;
         color: #111; line-height: 1.5; }}
  h1 {{ border-bottom: 3px solid #111; padding-bottom: .3rem; }}
  .actor {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem 1.25rem;
            margin: 1rem 0; page-break-inside: avoid; }}
  .conf {{ float: right; font-size: .8rem; background: #111; color: #fff;
           padding: .15rem .5rem; border-radius: 4px; }}
  .meta {{ color: #555; font-size: .85rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: .5rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: .35rem .5rem; text-align: left;
            font-size: .85rem; }}
  .mono {{ font-family: ui-monospace, monospace; word-break: break-all; }}
  .muted {{ color: #888; }}
  .summary li {{ display: inline-block; margin-right: 1rem; }}
  footer {{ margin-top: 2rem; color: #888; font-size: .8rem;
            border-top: 1px solid #ccc; padding-top: .5rem; }}
</style>
</head>
<body>
  <h1>Threat Actor Intelligence Report</h1>
  <p class="muted">Generated {_now()} · SIH26151 · TracePoint</p>
  <ul class="summary">
    <li><b>{summary['actors']}</b> actors</li>
    <li><b>{summary['observations']}</b> observations</li>
    <li><b>{summary['unique_identifiers']}</b> unique identifiers</li>
    <li><b>{summary['links']}</b> actor links</li>
  </ul>
  <p class="summary">{by_type}</p>
  {''.join(cards) or '<p class="muted">No actors recorded yet.</p>'}
  <footer>
    Correlations are investigative leads for trained human review,
    not identity conclusions. Attribution confidence is capped and
    reflects corroborating evidence only.
  </footer>
</body>
</html>"""


def _esc(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
