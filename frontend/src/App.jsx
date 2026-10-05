import * as d3 from "d3";
import { useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API_BASE =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000/api";

// True when the UI is talking to a remote backend (the Render deploy)
// rather than a local one. Used to show the free-tier notice.
const IS_HOSTED = !/localhost|127\.0\.0\.1/.test(API_BASE);

const NODE_COLORS = {
  username: "#2dd4bf",
  email: "#a78bfa",
  domain: "#38bdf8",
  url: "#60a5fa",
  ipv4: "#fbbf24",
  ipv6: "#f59e0b",
  btc_wallet: "#f59e0b",
  monero_wallet: "#fb923c",
  pgp_fingerprint: "#c084fc",
  telegram: "#38bdf8",
  unknown: "#94a3b8",
};

const NODE_NAMES = {
  username: "Username",
  email: "Email",
  domain: "Domain",
  url: "URL",
  ipv4: "IPv4 address",
  ipv6: "IPv6 address",
  btc_wallet: "Bitcoin wallet",
  monero_wallet: "Monero wallet",
  pgp_fingerprint: "PGP fingerprint",
  telegram: "Telegram handle",
  unknown: "Entity",
};

const SOURCE_NAMES = {
  github: "GitHub",
  gitlab: "GitLab",
  reddit: "Reddit",
  web: "Web",
  onion: "Tor / Onion",
  wayback: "Wayback",
  commoncrawl: "Common Crawl",
};

const SOURCE_ICONS = {
  github: "GH",
  gitlab: "GL",
  reddit: "RD",
  web: "WEB",
  onion: "TOR",
  wayback: "WB",
  commoncrawl: "CC",
};

const SOURCE_META = {
  github: {
    description: "Code, profiles and public repositories",
    tone: "surface",
  },
  gitlab: {
    description: "Public developer profiles and projects",
    tone: "surface",
  },
  reddit: {
    description: "Public discussions and posts",
    tone: "surface",
  },
  web: {
    description: "Direct public webpages",
    tone: "surface",
  },
  onion: {
    description: "Pages indexed by the background Tor crawler",
    tone: "onion",
  },
};

function shorten(value, maxLength = 34) {
  if (!value) return "Not available";

  const text = String(value);

  if (text.length <= maxLength) return text;

  const left = Math.ceil(maxLength / 2);
  const right = Math.floor(maxLength / 2) - 1;

  return `${text.slice(0, left)}…${text.slice(-right)}`;
}

function formatType(type) {
  return String(type || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value) {
  if (!value) return "Unknown";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function requestJson(path, options = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  }).then(async (response) => {
    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        payload.detail ||
          payload.message ||
          `Request failed with HTTP ${response.status}`,
      );
    }

    return payload;
  });
}

/* -------------------------------------------------------------------------- */
/* Graph                                                                       */
/* -------------------------------------------------------------------------- */

function buildGraphData(investigation) {
  const evidence = investigation?.evidence || [];
  const entities = investigation?.entities || [];

  const nodes = [];
  const links = [];

  const targetValue = investigation?.target?.value || "Target";
  const targetId = `target:${targetValue}`;

  nodes.push({
    id: targetId,
    label: targetValue,
    type: investigation?.target?.type || "username",
    root: true,
  });

  const entityIds = new Set();

  for (const entity of entities) {
    const id =
      entity.id || `entity:${entity.type}:${entity.normalized || entity.value}`;

    entityIds.add(id);

    nodes.push({
      id,
      label: entity.value || entity.normalized,
      type: entity.type || "unknown",
      root: false,
    });

    links.push({
      source: targetId,
      target: id,
      relation: "associated entity",
    });
  }

  for (const item of evidence) {
    const sourceId = `evidence:${item.id}`;

    nodes.push({
      id: sourceId,
      label: item.title || item.author || item.source || "Evidence",
      type: item.source_kind === "onion" ? "onion" : "unknown",
      evidence: true,
      source: item.source,
      sourceKind: item.source_kind,
      url: item.url,
      excerpt: item.excerpt,
    });

    links.push({
      source: targetId,
      target: sourceId,
      relation: "evidence",
    });

    for (const entity of item.entities || []) {
      const entityId =
        entity.id ||
        `entity:${entity.type}:${entity.normalized || entity.value}`;

      if (!entityIds.has(entityId)) {
        entityIds.add(entityId);

        nodes.push({
          id: entityId,
          label: entity.value || entity.normalized,
          type: entity.type || "unknown",
        });
      }

      links.push({
        source: sourceId,
        target: entityId,
        relation: "contains",
      });
    }
  }

  return { nodes, links };
}

function Graph({ investigation, selectedNode, setSelectedNode }) {
  const svgRef = useRef(null);
  const [resetToken, setResetToken] = useState(0);

  useEffect(() => {
    if (!svgRef.current || !investigation) return;

    const svg = d3.select(svgRef.current);

    const width = 900;
    const height = 520;

    svg.selectAll("*").remove();

    const { nodes, links } = buildGraphData(investigation);

    if (!nodes.length) return;

    const layer = svg.append("g").attr("class", "graph-layer");

    const defs = svg.append("defs");

    const glow = defs
      .append("radialGradient")
      .attr("id", "tracepointGraphGlow");

    glow.append("stop").attr("offset", "0%").attr("stop-opacity", 0.3);
    glow.append("stop").attr("offset", "100%").attr("stop-opacity", 0);

    layer
      .append("ellipse")
      .attr("cx", width / 2)
      .attr("cy", height / 2)
      .attr("rx", 330)
      .attr("ry", 215)
      .attr("fill", "url(#tracepointGraphGlow)");

    const zoom = d3
      .zoom()
      .scaleExtent([0.4, 3])
      .on("zoom", (event) => {
        layer.attr("transform", event.transform);
      });

    svg.call(zoom).on("dblclick.zoom", null);

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links)
          .id((node) => node.id)
          .distance((link) => {
            const source = nodes.find((n) => n.id === link.source.id);
            const target = nodes.find((n) => n.id === link.target.id);

            if (source?.root || target?.root) return 155;
            if (source?.evidence || target?.evidence) return 105;

            return 85;
          })
          .strength(0.55),
      )
      .force("charge", d3.forceManyBody().strength(-310))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3
          .forceCollide()
          .radius((node) => {
            if (node.root) return 48;
            if (node.evidence) return 34;
            return 26;
          }),
      )
      .alpha(1);

    const linkLayer = layer
      .append("g")
      .attr("class", "graph-links");

    const link = linkLayer
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", "graph-link");

    const nodeLayer = layer
      .append("g")
      .attr("class", "graph-nodes");

    const node = nodeLayer
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", "graph-node")
      .style("cursor", "grab")
      .on("click", (event, datum) => {
        event.stopPropagation();
        setSelectedNode({ ...datum });
      })
      .call(
        d3
          .drag()
          .on("start", (event, datum) => {
            if (!event.active) simulation.alphaTarget(0.25).restart();

            datum.fx = datum.x;
            datum.fy = datum.y;
          })
          .on("drag", (event, datum) => {
            datum.fx = event.x;
            datum.fy = event.y;
          })
          .on("end", (event, datum) => {
            if (!event.active) simulation.alphaTarget(0);

            datum.fx = null;
            datum.fy = null;
          }),
      );

    node
      .append("circle")
      .attr("class", "node-shadow")
      .attr("r", (datum) => {
        if (datum.root) return 40;
        if (datum.evidence) return 29;
        return 21;
      })
      .attr(
        "fill",
        (datum) =>
          NODE_COLORS[datum.type] ||
          (datum.evidence ? "#64748b" : NODE_COLORS.unknown),
      );

    node
      .append("circle")
      .attr("class", "node-core")
      .attr("r", (datum) => {
        if (datum.root) return 31;
        if (datum.evidence) return 21;
        return 15;
      })
      .attr(
        "fill",
        (datum) =>
          NODE_COLORS[datum.type] ||
          (datum.evidence ? "#64748b" : NODE_COLORS.unknown),
      );

    node
      .append("circle")
      .attr("class", "node-ring")
      .attr("r", (datum) => {
        if (datum.root) return 40;
        if (datum.evidence) return 29;
        return 21;
      });

    node
      .append("text")
      .attr("class", "node-label")
      .attr("y", (datum) => {
        if (datum.root) return 58;
        if (datum.evidence) return 43;
        return 35;
      })
      .text((datum) => shorten(datum.label, 25));

    node
      .append("title")
      .text(
        (datum) =>
          `${datum.root ? "Target" : datum.evidence ? "Evidence" : NODE_NAMES[datum.type] || "Entity"}: ${datum.label}`,
      );

    svg.on("click", () => setSelectedNode(null));

    simulation.on("tick", () => {
      link
        .attr("x1", (datum) => datum.source.x)
        .attr("y1", (datum) => datum.source.y)
        .attr("x2", (datum) => datum.target.x)
        .attr("y2", (datum) => datum.target.y);

      node.attr(
        "transform",
        (datum) => `translate(${datum.x} ${datum.y})`,
      );
    });

    return () => {
      simulation.stop();
      svg.on(".zoom", null);
    };
  }, [investigation, setSelectedNode, resetToken]);

  return (
    <div className="graph-wrapper">
      <div className="graph-toolbar">
        <div className="graph-metrics">
          <span>
            <b>{investigation?.evidence?.length || 0}</b> evidence
          </span>
          <span>
            <b>{investigation?.entities?.length || 0}</b> entities
          </span>
        </div>

        <button
          type="button"
          className="ghost-button"
          onClick={() => setResetToken((value) => value + 1)}
        >
          Reset graph
        </button>
      </div>

      <div className="graph-canvas">
        <svg
          ref={svgRef}
          viewBox="0 0 900 520"
          role="img"
          aria-label="Investigation relationship graph"
        />
      </div>

      <div className="graph-legend">
        <span>
          <i style={{ background: NODE_COLORS.username }} />
          Identity
        </span>
        <span>
          <i style={{ background: NODE_COLORS.email }} />
          Email
        </span>
        <span>
          <i style={{ background: NODE_COLORS.domain }} />
          Domain
        </span>
        <span>
          <i style={{ background: NODE_COLORS.pgp_fingerprint }} />
          PGP
        </span>
        <span>
          <i style={{ background: "#64748b" }} />
          Evidence
        </span>
      </div>

      <p className="graph-hint">
        Drag nodes · click a node · scroll to zoom
      </p>

      {selectedNode && (
        <div className="selected-node">
          <div>
            <span className="selected-label">
              {selectedNode.root
                ? "INVESTIGATION TARGET"
                : selectedNode.evidence
                  ? "EVIDENCE"
                  : NODE_NAMES[selectedNode.type] || "ENTITY"}
            </span>

            <strong>{selectedNode.label}</strong>

            <small>
              {selectedNode.evidence
                ? `${selectedNode.source || "Unknown source"} · ${selectedNode.sourceKind || "evidence"}`
                : selectedNode.root
                  ? "Root investigation target"
                  : formatType(selectedNode.type)}
            </small>
          </div>

          {selectedNode.url && (
            <a
              href={selectedNode.url}
              target="_blank"
              rel="noreferrer"
            >
              Open source ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* UI components                                                               */
/* -------------------------------------------------------------------------- */

function SourceStatus({ run }) {
  const status = run.status || "unknown";

  return (
    <div className={`source-status ${status}`}>
      <div className="source-status-main">
        <span className="source-symbol">
          {SOURCE_ICONS[run.source] || "??"}
        </span>

        <div>
          <strong>{SOURCE_NAMES[run.source] || run.source}</strong>
          <small>{run.category || "collector"}</small>
        </div>
      </div>

      <div className="source-status-result">
        <span className="status-indicator" />
        <span>{status}</span>
        <b>{run.result_count || 0}</b>
      </div>
    </div>
  );
}

function Stat({ value, label }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

// High-value identifiers first; these are the actual de-anonymizing
// evidence. Lower-value context identifiers follow.
const IDENTIFIER_ORDER = [
  "pgp_fingerprint",
  "btc_wallet",
  "monero_wallet",
  "email",
  "telegram",
  "domain",
  "ipv4",
  "ipv6",
  "username",
  "url",
  "unknown",
];

function groupEntities(entities = []) {
  const groups = {};

  for (const entity of entities) {
    const type = entity.type || "unknown";
    (groups[type] ||= []).push(entity);
  }

  return IDENTIFIER_ORDER.filter((type) => groups[type]?.length).map(
    (type) => ({ type, items: groups[type] }),
  );
}

function IdentifierLedger({ entities }) {
  const groups = groupEntities(entities);

  if (!groups.length) {
    return <p className="empty-state">No identifiers extracted.</p>;
  }

  return (
    <div className="identifier-groups">
      {groups.map(({ type, items }) => {
        const color = NODE_COLORS[type] || NODE_COLORS.unknown;

        return (
          <div className="identifier-group" key={type}>
            <div className="identifier-group-head">
              <span
                className="entity-marker"
                style={{ background: color, boxShadow: `0 0 10px ${color}` }}
              />
              <strong>{NODE_NAMES[type] || formatType(type)}</strong>
              <span className="panel-count">{items.length}</span>
            </div>

            <ul className="identifier-values">
              {items.map((entity) => (
                <li
                  key={entity.id}
                  className="identifier-value"
                  title={entity.value}
                >
                  {entity.value}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function EvidenceCard({ item }) {
  const isOnion =
    String(item.source_kind || "").toLowerCase() === "onion";

  return (
    <article className={`evidence-card ${isOnion ? "onion-evidence" : ""}`}>
      <div className="evidence-top">
        <div className="evidence-source">
          <span className="evidence-source-icon">
            {isOnion
              ? "TOR"
              : SOURCE_ICONS[
                  String(item.source_kind || "").toLowerCase()
                ] || "EV"}
          </span>

          <div>
            <strong>{item.title || "Untitled evidence"}</strong>
            <small>
              {item.source || "Unknown source"} ·{" "}
              {formatType(item.evidence_type)}
            </small>
          </div>
        </div>

        {item.url && (
          <a href={item.url} target="_blank" rel="noreferrer">
            Open ↗
          </a>
        )}
      </div>

      {item.excerpt && (
        <p className="evidence-excerpt">{item.excerpt}</p>
      )}

      <div className="evidence-meta">
        <span>
          {item.entities?.length || 0} extracted entities
        </span>

        <span>
          {item.metadata?.network
            ? `Network: ${item.metadata.network}`
            : `Collected: ${formatDate(item.collected_at)}`}
        </span>

        {item.metadata?.mentions !== undefined && (
          <span>
            {item.metadata.mentions} mention
            {item.metadata.mentions === 1 ? "" : "s"} of “{item.metadata.alias}”
          </span>
        )}

        {item.metadata?.mirrors?.length > 0 && (
          <span title={item.metadata.mirrors.join("\n")}>
            +{item.metadata.mirrors.length} mirror
            {item.metadata.mirrors.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
    </article>
  );
}

/* -------------------------------------------------------------------------- */
/* App                                                                         */
/* -------------------------------------------------------------------------- */

export default function App() {
  const [query, setQuery] = useState("");
  const [investigation, setInvestigation] = useState(null);

  const [apiOnline, setApiOnline] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const [selectedNode, setSelectedNode] = useState(null);
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("tracepoint-theme") || "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("tracepoint-theme", theme);
    } catch {
      // Ignore storage failures.
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };

  const [sources, setSources] = useState({
    github: true,
    gitlab: true,
    reddit: false,
    web: true,
    onion: true,
  });

  const [maxResults, setMaxResults] = useState(5);

  const sourceList = useMemo(
    () =>
      Object.entries(sources)
        .filter(([, enabled]) => enabled)
        .map(([source]) => source),
    [sources],
  );

  const checkHealth = async () => {
    try {
      const health = await requestJson("/health");
      setApiOnline(health.status === "ok");
      return health;
    } catch {
      setApiOnline(false);
      return null;
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  const handleInvestigate = async (event) => {
    event.preventDefault();

    const target = query.trim();

    if (!target) {
      setMessage("Enter a target to investigate.");
      return;
    }

    if (!sourceList.length) {
      setMessage("Select at least one collection source.");
      return;
    }

    setLoading(true);
    setMessage("");
    setInvestigation(null);
    setSelectedNode(null);

    try {
      const result = await requestJson("/search", {
        method: "POST",
        body: JSON.stringify({
          query: target,
          sources: sourceList,
          max_results: Number(maxResults),
        }),
      });

      setInvestigation(result);
      setApiOnline(true);
    } catch (error) {
      setMessage(error.message);
      setApiOnline(false);
    } finally {
      setLoading(false);
    }
  };

  const toggleSource = (source) => {
    setSources((current) => ({
      ...current,
      [source]: !current[source],
    }));
  };

  const successfulCollectors =
    investigation?.collection_runs?.filter(
      (run) => run.status === "success",
    ).length || 0;

  const blockedCollectors =
    investigation?.collection_runs?.filter(
      (run) => run.status === "blocked",
    ).length || 0;

  const failedCollectors =
    investigation?.collection_runs?.filter(
      (run) => run.status === "error" || run.status === "timeout",
    ).length || 0;

  const onionEvidence =
    investigation?.evidence?.filter(
      (item) =>
        String(item.source_kind || "").toLowerCase() === "onion",
    ).length || 0;

  return (
    <main className="app-shell">
      {/* Header */}
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">◈</div>

          <div>
            <div className="brand-name">TRACEPOINT</div>
            <div className="brand-subtitle">
              THREAT INTELLIGENCE WORKSTATION
            </div>
          </div>
        </div>

        <div className="topbar-right">
          <span className="case-id">
            {investigation ? "ACTIVE CASE" : "READY"}
          </span>

          <span className={`api-status ${apiOnline ? "online" : "offline"}`}>
            <i />
            {apiOnline ? "API ONLINE" : "API OFFLINE"}
          </span>

          <button
            type="button"
            className="theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            <span className="theme-toggle-icon" aria-hidden="true">
              {theme === "dark" ? "☀" : "☾"}
            </span>
            <span>{theme === "dark" ? "LIGHT" : "DARK"}</span>
          </button>
        </div>
      </header>

      {/* Hosted-backend notice */}
      {IS_HOSTED && (
        <div className="hosting-note">
          <span className="hosting-note-icon" aria-hidden="true">ⓘ</span>
          <span>
            This live demo's backend runs on <strong>Render's free
            tier</strong>, so results are limited and searches are slower.
            Run the project locally to see its full performance and data.
          </span>
        </div>
      )}

      {/* Hero */}
      {!investigation && !loading && (
        <section className="hero">
          <div className="hero-kicker">
            <span />
            SIH26151 · INVESTIGATION WORKSPACE
          </div>

          <h1>
            Correlate the traces.
            <br />
            <span>Review the evidence.</span>
          </h1>

          <p>
            TracePoint collects public-source intelligence, extracts
            technical indicators, and maps relationships between
            discovered entities.
          </p>
        </section>
      )}

      {/* Search */}
      <section className="investigation-bar">
        <form onSubmit={handleInvestigate}>
          <div className="target-input">
            <span className="input-prefix">TARGET</span>

            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="username, handle, domain, email..."
              autoComplete="off"
            />

            <button type="submit" disabled={loading}>
              {loading ? "COLLECTING..." : "INVESTIGATE"}
            </button>
          </div>
        </form>

        <div className="source-selector">
          <div className="source-selector-title">
            <span>COLLECTION SOURCES</span>
            <small>{sourceList.length} enabled</small>
          </div>

          <div className="source-grid">
            {Object.entries(sources).map(([source, enabled]) => {
              const meta = SOURCE_META[source];

              return (
                <button
                  key={source}
                  type="button"
                  className={`source-card ${
                    enabled ? "enabled" : ""
                  } ${meta?.tone === "onion" ? "onion-source" : ""}`}
                  onClick={() => toggleSource(source)}
                >
                  <div className="source-card-top">
                    <span className="source-card-icon">
                      {SOURCE_ICONS[source]}
                    </span>

                    <span
                      className={`source-check ${
                        enabled ? "checked" : ""
                      }`}
                    >
                      {enabled ? "✓" : ""}
                    </span>
                  </div>

                  <strong>{SOURCE_NAMES[source]}</strong>

                  <small>
                    {meta?.description || "Public source"}
                  </small>
                </button>
              );
            })}
          </div>

          <div className="collection-options">
            <label>
              <span>MAX RESULTS / SOURCE</span>

              <select
                value={maxResults}
                onChange={(event) =>
                  setMaxResults(event.target.value)
                }
              >
                <option value={5}>5</option>
                <option value={10}>10</option>
                <option value={20}>20</option>
              </select>
            </label>

            <span className="endpoint">
              {IS_HOSTED ? "HOSTED (RENDER FREE)" : "LOCAL ENGINE"} · {API_BASE}
            </span>
          </div>
        </div>
      </section>

      {message && (
        <div className="error-banner">
          <span>!</span>
          {message}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <section className="loading-panel">
          <div className="loading-header">
            <div>
              <span className="section-kicker">LIVE COLLECTION</span>
              <h2>Gathering intelligence</h2>
              {sources.onion && (
                <small>
                  Hunting the alias across onion services — this can
                  take up to a minute.
                </small>
              )}
            </div>

            <span className="live-pill">
              <i />
              RUNNING
            </span>
          </div>

          <div className="loading-track">
            <span />
          </div>

          <div className="loading-sources">
            {sourceList.map((source) => (
              <span key={source}>
                <i />
                {SOURCE_NAMES[source]}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Investigation */}
      {investigation && (
        <>
          {/* Case header */}
          <section className="case-header">
            <div className="case-title">
              <span className="section-kicker">
                ACTIVE INVESTIGATION
              </span>

              <h2>{investigation.target?.value}</h2>

              <div className="case-meta">
                <span>
                  TARGET TYPE ·{" "}
                  <b>{investigation.target?.type || "unknown"}</b>
                </span>

                <span>STATUS · {investigation.status}</span>
              </div>
            </div>

            <div className="case-stats">
              <Stat
                value={investigation.evidence?.length || 0}
                label="Evidence"
              />

              <Stat
                value={investigation.entities?.length || 0}
                label="Entities"
              />

              <Stat
                value={successfulCollectors}
                label="Sources OK"
              />

              <Stat
                value={onionEvidence}
                label="Tor Evidence"
              />
            </div>
          </section>

          {/* Collection strip */}
          <section className="collection-panel">
            <div className="panel-heading">
              <div>
                <span className="section-kicker">
                  COLLECTION TELEMETRY
                </span>
                <h3>Source activity</h3>
              </div>

              <span className="panel-count">
                {investigation.collection_runs?.length || 0} collectors
              </span>
            </div>

            <div className="collector-grid">
              {(investigation.collection_runs || []).map((run) => (
                <SourceStatus
                  key={`${run.source}-${run.started_at}`}
                  run={run}
                />
              ))}
            </div>

            {(blockedCollectors > 0 || failedCollectors > 0) && (
              <div className="collection-note">
                {blockedCollectors > 0 && (
                  <span>
                    {blockedCollectors} source
                    {blockedCollectors === 1 ? "" : "s"} blocked
                  </span>
                )}

                {failedCollectors > 0 && (
                  <span>
                    {failedCollectors} collector
                    {failedCollectors === 1 ? "" : "s"} failed
                  </span>
                )}

                <small>
                  Collector availability does not invalidate other
                  collected evidence.
                </small>
              </div>
            )}
          </section>

          {/* Main intelligence grid */}
          <section className="intelligence-grid">
            <article className="panel graph-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">
                    ENTITY RELATIONSHIPS
                  </span>
                  <h3>Investigation graph</h3>
                </div>

                <span className="panel-count">D3 · LIVE</span>
              </div>

              <Graph
                investigation={investigation}
                selectedNode={selectedNode}
                setSelectedNode={setSelectedNode}
              />
            </article>

            <aside className="side-column">
              <article className="panel identifier-panel">
                <div className="panel-heading">
                  <div>
                    <span className="section-kicker">
                      IDENTIFIER LEDGER
                    </span>
                    <h3>Extracted identifiers</h3>
                  </div>

                  <span className="panel-count">
                    {investigation.entities?.length || 0}
                  </span>
                </div>

                <IdentifierLedger entities={investigation.entities} />
              </article>

              <article className="signal-card">
                <div className="signal-header">
                  <span className="section-kicker">
                    INVESTIGATION NOTE
                  </span>

                  <span>REVIEW</span>
                </div>

                <strong>Evidence is not identity.</strong>

                <p>
                  Correlated signals should be reviewed against their
                  underlying sources before drawing attribution
                  conclusions.
                </p>
              </article>
            </aside>
          </section>

          {/* Evidence */}
          <section className="panel evidence-panel">
            <div className="panel-heading">
              <div>
                <span className="section-kicker">
                  PROVENANCE LEDGER
                </span>
                <h3>Collected evidence</h3>
              </div>

              <span className="panel-count">
                {investigation.evidence?.length || 0} records
              </span>
            </div>

            <div className="evidence-list">
              {(investigation.evidence || []).length ? (
                investigation.evidence.map((item) => (
                  <EvidenceCard
                    key={item.id}
                    item={item}
                  />
                ))
              ) : (
                <p className="empty-state">
                  No evidence was returned.
                </p>
              )}
            </div>
          </section>
        </>
      )}

      {!investigation && !loading && (
        <section className="ready-panel">
          <div className="ready-mark">◈</div>

          <span className="section-kicker">TRACEPOINT READY</span>

          <h3>Start an investigation</h3>

          <p>
            Enter a public identifier and select the collection
            sources you want to investigate.
          </p>

          <div className="ready-flow">
            <span>COLLECT</span>
            <b>→</b>
            <span>EXTRACT</span>
            <b>→</b>
            <span>CORRELATE</span>
            <b>→</b>
            <span>REVIEW</span>
          </div>
        </section>
      )}

      <footer>
        TRACEPOINT · SIH26151 · PUBLIC-SOURCE INVESTIGATION WORKSTATION
      </footer>
    </main>
  );
}