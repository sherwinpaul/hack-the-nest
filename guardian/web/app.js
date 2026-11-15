/* Trip Guardian dashboard — vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const SVGNS = "http://www.w3.org/2000/svg";
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const AGENTS = [
    { key: "orchestrator", name: "Trip Guardian", color: "var(--amber)" },
    { key: "weather", name: "Weather Risk", color: "var(--cyan)", tool: "weather_risk" },
    { key: "intel", name: "Web Intel", color: "var(--violet)", tool: "web_intel" },
    { key: "fares", name: "Fare Search", color: "var(--green)", tool: "fare_search" },
    { key: "scoring", name: "Scoring Engine", color: "#ffffff", tool: "rank_options", model: "deterministic code" },
    { key: "comms", name: "Comms", color: "var(--pink)", tool: "draft_host_message" },
  ];
  const AGENT_COLOR = Object.fromEntries(AGENTS.map((a) => [a.name, a.color]));
  AGENT_COLOR["Key pool"] = "var(--amber)";
  const TOOL_TO_AGENT = Object.fromEntries(AGENTS.filter((a) => a.tool).map((a) => [a.tool, a]));

  let state = null;
  let selectedId = null;
  let running = false;

  // ---------- formatting ----------
  const fmtUSD = (n) => "$" + Math.round(n).toLocaleString("en-US");
  const fmtTime = (iso) => {
    const d = new Date(iso);
    const day = d.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" }).toUpperCase();
    const hm = d.toISOString().slice(11, 16);
    return `${day} ${hm}Z`;
  };
  const pctColor = (p) => (p >= 0.8 ? "var(--green)" : p >= 0.6 ? "var(--amber)" : "var(--red)");
  const riskColor = (r) => (r >= 0.5 ? "var(--red)" : r >= 0.2 ? "var(--amber)" : "var(--green)");
  const flightLabel = (o) => {
    const first = o.legs[0].flight_no || o.legs[0].carrier;
    return o.legs.length > 1 ? `${first} +${o.legs.length - 1}` : first;
  };

  // ---------- top bar + countdown ----------
  function renderHeader() {
    const c = state.commitment;
    $("#mission-title").textContent = `${c.title} · ${c.city}`;
    $("#mode-chip").textContent = state.mode.toUpperCase();
    $("#stake-value").textContent = fmtUSD(c.meeting_value_usd);
    $("#stake-sub").textContent = `on the line if you miss “${c.title}”`;
    $("#stake-dest").textContent = `${c.airport} · ${c.city}`;
    $("#stake-deadline").textContent = fmtTime(c.must_arrive_by);
    $("#stake-budget").textContent = `+${fmtUSD(c.max_extra_spend_usd)}`;
  }

  function tickCountdown() {
    if (!state) return;
    const ms = new Date(state.commitment.must_arrive_by) - Date.now();
    const el = $("#countdown");
    if (ms <= 0) { el.textContent = "DEADLINE PASSED"; return; }
    const s = Math.floor(ms / 1000);
    const d = Math.floor(s / 86400);
    const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, "0");
    const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    el.textContent = `${d}D ${hh}:${mm}:${ss}`;
  }

  // ---------- annunciators ----------
  function renderAnnunciators() {
    const routing = state.routing || {};
    $("#annunciators").innerHTML = AGENTS.map((a) => {
      const model = a.model || (routing[a.key] || "").split(":").slice(1).join(":") || "—";
      return `<div class="ann" id="ann-${a.key}" style="--c:${a.color}">
        <span class="lamp"></span>
        <div style="min-width:0"><div class="ann-name">${esc(a.name)}</div><div class="ann-model">${esc(model)}</div></div>
      </div>`;
    }).join("");
  }
  function setAnn(key, status) {
    const el = $(`#ann-${key}`);
    if (!el) return;
    el.classList.remove("working", "done");
    if (status) el.classList.add(status);
  }

  // ---------- radar map ----------
  function project(coords, W, H, pad) {
    const pts = Object.values(coords).filter(Boolean);
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    const minLat = Math.min(...lats) - 1.4, maxLat = Math.max(...lats) + 1.4;
    const minLon = Math.min(...lons) - 1.8, maxLon = Math.max(...lons) + 1.8;
    const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const scale = Math.min((W - pad * 2) / ((maxLon - minLon) * k), (H - pad * 2) / (maxLat - minLat));
    const ox = (W - (maxLon - minLon) * k * scale) / 2;
    const oy = (H - (maxLat - minLat) * scale) / 2;
    const fn = ([lat, lon]) => [ox + (lon - minLon) * k * scale, oy + (maxLat - lat) * scale];
    fn.bounds = { minLat, maxLat, minLon, maxLon };
    return fn;
  }

  function svg(tag, attrs = {}, parent) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }

  function legPath(a, b, bend) {
    const [x1, y1] = a, [x2, y2] = b;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const cx = mx - (dy / len) * len * bend, cy = my + (dx / len) * len * bend;
    return `Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }

  function renderRadar() {
    const root = $("#radar");
    root.innerHTML = "";
    const W = 800, H = 440;
    const P = project(state.coords, W, H, 44);
    const defs = svg("defs", {}, root);
    const g = svg("radialGradient", { id: "stormGrad" }, defs);
    svg("stop", { offset: "0%", "stop-color": "#ff5d6c", "stop-opacity": "0.55" }, g);
    svg("stop", { offset: "55%", "stop-color": "#ff5d6c", "stop-opacity": "0.16" }, g);
    svg("stop", { offset: "100%", "stop-color": "#ff5d6c", "stop-opacity": "0" }, g);

    // graticule
    const { minLat, maxLat, minLon, maxLon } = P.bounds;
    for (let lon = Math.ceil(minLon / 2) * 2; lon <= maxLon; lon += 2) {
      const [x1, y1] = P([maxLat, lon]), [x2, y2] = P([minLat, lon]);
      svg("line", { x1, y1, x2, y2, class: "grat" }, root);
    }
    for (let lat = Math.ceil(minLat / 2) * 2; lat <= maxLat; lat += 2) {
      const [x1, y1] = P([lat, minLon]), [x2, y2] = P([lat, maxLon]);
      svg("line", { x1, y1, x2, y2, class: "grat" }, root);
    }
    for (const r of [90, 170, 250, 330]) svg("circle", { cx: W / 2, cy: H / 2, r, class: "ring" }, root);

    // storm cells
    for (const [code, risk] of Object.entries(state.risks)) {
      const c = state.coords[code];
      if (!c || risk.disruption_prob < 0.25) continue;
      const [x, y] = P(c);
      const r = 26 + 96 * risk.disruption_prob;
      svg("circle", { cx: x, cy: y, r, fill: "url(#stormGrad)", class: "storm" }, root);
      for (const delay of [0, 1.4]) {
        const ring = svg("circle", { cx: x, cy: y, r: r * 0.7, class: "storm-ring" }, root);
        ring.style.animationDelay = `${delay}s`;
      }
    }

    // routes — alternatives first, then current, then pick on top
    const ranking = state.ranking;
    const pickId = ranking[0]?.option.id;
    const currentId = state.current_trip.id;
    const order = [...ranking].sort((a, b) => weight(a.option.id) - weight(b.option.id));
    function weight(id) { return id === pickId ? 2 : id === currentId ? 1 : 0; }
    order.forEach((r) => {
      const o = r.option;
      const idx = ranking.findIndex((x) => x.option.id === o.id);
      const bend = (idx % 2 ? -1 : 1) * (0.08 + 0.05 * Math.floor(idx / 2));
      let d = "";
      o.legs.forEach((leg, i) => {
        const a = P(state.coords[leg.origin]), b = P(state.coords[leg.destination]);
        if (i === 0) d += `M ${a[0].toFixed(1)} ${a[1].toFixed(1)} `;
        d += legPath(a, b, o.id === pickId ? -0.2 : bend) + " ";
      });
      const cls = o.id === pickId ? "pick" : o.id === currentId ? "current" : "alt";
      svg("path", { d, class: `route ${cls}`, "data-id": o.id, id: `route-${o.id}` }, root);
    });

    // plane on the guardian pick
    if (pickId) {
      const plane = svg("path", { d: "M -7 -2.2 L 3 -2.2 L 8 0 L 3 2.2 L -7 2.2 L -5 0 Z M -1 -2.2 L -4 -7 L -2 -7 L 3 -2.2 M -1 2.2 L -4 7 L -2 7 L 3 2.2", class: "plane" }, root);
      const anim = svg("animateMotion", { dur: "5s", repeatCount: "indefinite", rotate: "auto" }, plane);
      svg("mpath", { href: `#route-${pickId}` }, anim);
    }

    // airports
    for (const [code, c] of Object.entries(state.coords)) {
      if (!c) continue;
      const [x, y] = P(c);
      const risk = state.risks[code]?.disruption_prob ?? 0;
      const col = riskColor(risk);
      svg("circle", { cx: x, cy: y, r: 6.5, class: "node", stroke: col }, root);
      svg("circle", { cx: x, cy: y, r: 2.4, fill: col }, root);
      const t = svg("text", { x, y: y - 14, "text-anchor": "middle", class: "code" }, root);
      t.textContent = code;
      const rt = svg("text", { x, y: y + 22, "text-anchor": "middle", class: "risk", fill: col }, root);
      rt.textContent = `${Math.round(risk * 100)}% risk`;
      const title = svg("title", {}, rt);
      title.textContent = state.risks[code]?.reason || "";
    }
  }

  function highlightRoute(id) {
    document.querySelectorAll("#radar .route").forEach((p) => {
      p.classList.toggle("hl", !!id && p.dataset.id === id && !p.classList.contains("pick"));
      p.classList.toggle("dim", !!id && p.dataset.id !== id);
    });
  }

  // ---------- dials ----------
  function dial(el, p, caption, sub) {
    const pct = Math.round(p * 100);
    const ticks = Array.from({ length: 11 }, (_, i) => {
      const a = Math.PI * (1 - i / 10);
      const x1 = 80 + Math.cos(a) * 58, y1 = 80 - Math.sin(a) * 58;
      const x2 = 80 + Math.cos(a) * 64, y2 = 80 - Math.sin(a) * 64;
      return `<line class="tick" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
    }).join("");
    el.innerHTML = `
      <svg viewBox="0 0 160 100">
        ${ticks}
        <path class="track" d="M 30 80 A 50 50 0 0 1 130 80" pathLength="100"/>
        <path class="value" d="M 30 80 A 50 50 0 0 1 130 80" pathLength="100"
          stroke="${pctColor(p)}" stroke-dasharray="100" stroke-dashoffset="100"
          style="filter: drop-shadow(0 0 6px ${pctColor(p)})"/>
        <text class="pct" x="80" y="78" text-anchor="middle">${pct}%</text>
      </svg>
      <figcaption>${esc(caption)}<b>${esc(sub)}</b></figcaption>`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      el.querySelector(".value").setAttribute("stroke-dashoffset", String(100 - pct));
    }));
  }

  function renderDials() {
    const cur = state.ranking.find((r) => r.option.id === state.current_trip.id);
    const pick = state.ranking[0];
    dial($("#dial-current"), cur ? cur.p_on_time : 0, "BOOKED ROUTE", cur ? state.current_trip.airports.join("–") : "—");
    dial($("#dial-pick"), pick.p_on_time, "GUARDIAN PICK", `${flightLabel(pick.option)} · +${fmtUSD(pick.extra_cost_usd)}`);
  }

  // ---------- departure board ----------
  function statusFor(r, i) {
    if (r.p_on_time === 0) return ["late", "TOO LATE"];
    if (i === 0) return ["pick", "GUARDIAN PICK"];
    if (r.option.id === state.current_trip.id) return ["booked", "BOOKED"];
    return r.p_on_time >= 0.8 ? ["ok", "ON TIME"] : ["risk", "AT RISK"];
  }

  const flap = (text) => `<span class="flap" data-final="${esc(text)}">${[...text].map((ch) => `<b>${ch === " " ? "&nbsp;" : esc(ch)}</b>`).join("")}</span>`;

  function renderBoard() {
    const rows = state.ranking.map((r, i) => {
      const o = r.option;
      const [cls, label] = statusFor(r, i);
      return `<div class="brow${o.id === selectedId ? " selected" : ""}" role="row" data-id="${esc(o.id)}" style="animation-delay:${i * 60}ms">
        <span class="rank">${String(i + 1).padStart(2, "0")}</span>
        <span>${flap(o.legs[0].flight_no || o.legs[0].carrier)}</span>
        <span class="route-txt">${esc(o.airports.join(" › "))}<span class="stops">${o.legs.length > 1 ? `${o.legs.length - 1} stop · via ${esc(o.airports.slice(1, -1).join(", "))}` : "nonstop"}</span></span>
        <span class="time">${esc(fmtTime(o.arrive))}</span>
        <span class="pbar"><span class="bar"><span class="fill" style="width:0;background:${pctColor(r.p_on_time)}" data-w="${(r.p_on_time * 100).toFixed(0)}%"></span></span><span>${Math.round(r.p_on_time * 100)}%</span></span>
        <span class="cost">${r.extra_cost_usd ? "+" + fmtUSD(r.extra_cost_usd) : "—"}</span>
        <span class="loss" style="color:${i === 0 ? "var(--green)" : "var(--ink)"}">${fmtUSD(r.expected_loss_usd)}</span>
        <span class="status ${cls}">${label}</span>
      </div>`;
    }).join("");
    $("#board").innerHTML = `<div class="brow head" role="row">
        <span>#</span><span>FLIGHT</span><span>ROUTE</span><span>ARRIVES</span><span>P(ON TIME)</span><span style="text-align:right">+COST</span><span style="text-align:right">EXP. LOSS</span><span style="text-align:center">STATUS</span>
      </div>` + rows;

    requestAnimationFrame(() => document.querySelectorAll(".pbar .fill").forEach((f) => (f.style.width = f.dataset.w)));
    scrambleFlaps();
    document.querySelectorAll(".brow[data-id]").forEach((row) => {
      row.addEventListener("click", () => selectOption(row.dataset.id));
      row.addEventListener("mouseenter", () => highlightRoute(row.dataset.id));
      row.addEventListener("mouseleave", () => highlightRoute(null));
    });
    updateSelection();
  }

  function scrambleFlaps() {
    const CH = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789";
    document.querySelectorAll(".flap").forEach((f, fi) => {
      const final = [...f.dataset.final];
      const cells = [...f.children];
      cells.forEach((cell, ci) => {
        if (final[ci] === " ") return;
        let n = 6 + ci * 2 + fi * 2;
        const t = setInterval(() => {
          cell.textContent = --n <= 0 ? final[ci] : CH[(Math.random() * CH.length) | 0];
          if (n <= 0) clearInterval(t);
        }, 45);
      });
    });
  }

  function selectOption(id) {
    selectedId = id;
    document.querySelectorAll(".brow[data-id]").forEach((r) => r.classList.toggle("selected", r.dataset.id === id));
    updateSelection();
  }

  function updateSelection() {
    const r = state.ranking.find((x) => x.option.id === selectedId);
    const btn = $("#approve");
    if (!r) { $("#selected-label").textContent = "Select an option"; btn.disabled = true; return; }
    const isCurrent = r.option.id === state.current_trip.id;
    $("#selected-label").innerHTML = `Selected <b>${esc(flightLabel(r.option))}</b> · ${esc(r.option.airports.join(" › "))} · <b>${Math.round(r.p_on_time * 100)}%</b> on time · ${esc(fmtUSD(r.option.price_usd))}`;
    btn.disabled = isCurrent || r.p_on_time === 0;
    btn.textContent = isCurrent ? "ALREADY BOOKED" : "APPROVE & BOOK";
  }

  // ---------- approval ----------
  function approve() {
    const r = state.ranking.find((x) => x.option.id === selectedId);
    if (!r) return;
    $("#confirm-title").textContent = `${flightLabel(r.option)} · ${r.option.airports.join(" › ")}`;
    $("#confirm-body").textContent =
      `${fmtUSD(r.option.price_usd)} via ${r.option.source}. Arrives ${fmtTime(r.option.arrive)} with ${Math.round(r.p_on_time * 100)}% chance of making it on time. ` +
      (state.mode === "replay" ? "Replay mode: booking is simulated." : "Duffel test mode only.");
    const dlg = $("#confirm");
    dlg.returnValue = "";
    dlg.showModal();
    dlg.addEventListener("close", async function onClose() {
      dlg.removeEventListener("close", onClose);
      if (dlg.returnValue !== "ok") return;
      try {
        const res = await fetch("/api/approve", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ option_id: r.option.id }),
        });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || res.statusText);
        toast(`✓ ${body.message}`);
      } catch (e) {
        toast(`Booking failed: ${e.message}`, true);
      }
    });
  }

  function toast(msg, err = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.toggle("err", err);
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), 5000);
  }

  // ---------- live run ----------
  let runStart = 0;
  function recAdd(type, agent, html) {
    const list = $("#recorder");
    list.querySelector(".rec-empty")?.remove();
    const li = document.createElement("li");
    li.className = `rec-item ${type}`;
    li.style.setProperty("--c", AGENT_COLOR[agent] || "var(--ink-2)");
    const t = ((performance.now() - runStart) / 1000).toFixed(1);
    li.innerHTML = `<span class="t">${t}s</span><span class="dot"></span><div class="body"><div class="who">${esc(agent)}</div><div class="what">${html}</div></div>`;
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
  }

  const pretty = (s) => {
    try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; }
  };
  const detail = (label, body) =>
    body && body !== "{}" ? `<details><summary>${esc(label)}</summary><pre>${esc(pretty(body))}</pre></details>` : "";

  function handleEvent(ev) {
    switch (ev.type) {
      case "agent":
        if (ev.agent === "Trip Guardian") setAnn("orchestrator", "working");
        break;
      case "tool_called": {
        const a = TOOL_TO_AGENT[ev.tool];
        if (a && ev.agent === "Trip Guardian") setAnn(a.key, "working");
        recAdd("tool_called", ev.agent, `calls <code>${esc(ev.tool)}</code>${detail("arguments", ev.args)}`);
        break;
      }
      case "tool_output": {
        const a = TOOL_TO_AGENT[ev.tool];
        if (a && ev.agent === "Trip Guardian") setAnn(a.key, "done");
        if (ev.tool === "draft_host_message") {
          $("#host-msg").value = ev.output;
          $("#copy-host").disabled = false;
        }
        recAdd("tool_output", ev.agent, `result from <code>${esc(ev.tool)}</code>${detail("output", ev.output)}`);
        break;
      }
      case "message":
        recAdd("message", ev.agent, `${esc(ev.text.slice(0, 140))}${ev.text.length > 140 ? "…" : ""}${ev.text.length > 140 ? detail("full answer", ev.text) : ""}`);
        break;
      case "system":
        recAdd("system", ev.agent, esc(ev.text));
        break;
      case "error":
        recAdd("error", "Error", esc(ev.text));
        break;
      case "final":
        setAnn("orchestrator", "done");
        $("#brief").innerHTML = DOMPurify.sanitize(marked.parse(ev.text || ""));
        recAdd("tool_output", "Trip Guardian", "recommendation ready — awaiting your approval");
        break;
    }
  }

  function engage() {
    if (running) return;
    running = true;
    runStart = performance.now();
    $("#recorder").innerHTML = "";
    $("#brief").innerHTML = `<p class="muted">Agents are working…</p>`;
    AGENTS.forEach((a) => setAnn(a.key, null));
    $("#engage").disabled = true;
    $("#engage-label").textContent = "GUARDIAN ACTIVE";
    const rec = $("#rec-indicator");
    rec.className = "rec live";
    rec.innerHTML = "<i></i>RECORDING";

    const es = new EventSource("/api/run");
    let failed = false;
    const finish = (ok) => {
      es.close(); // EventSource reconnects by default, which would start a second run
      running = false;
      $("#engage").disabled = false;
      $("#engage-label").textContent = "RE-RUN GUARDIAN";
      rec.className = ok ? "rec done" : "rec live";
      rec.innerHTML = ok ? "<i></i>COMPLETE" : "<i></i>FAILED";
      if (!ok && !$("#brief").querySelector("h1,h2,h3,ul")) {
        $("#brief").innerHTML = `<p class="muted">The run stopped before a recommendation. See the flight recorder for details.</p>`;
      }
    };
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "done") return finish(!failed);
      if (ev.type === "error") failed = true;
      handleEvent(ev);
    };
    es.onerror = () => {
      if (running) { recAdd("error", "Error", "Lost connection to the server."); finish(false); }
    };
  }

  // ---------- boot ----------
  async function boot() {
    try {
      state = await (await fetch("/api/state")).json();
    } catch (e) {
      toast(`Could not load state: ${e.message}`, true);
      return;
    }
    selectedId = state.ranking[0]?.option.id ?? null;
    renderHeader();
    renderAnnunciators();
    renderRadar();
    renderDials();
    renderBoard();
    tickCountdown();
    setInterval(tickCountdown, 1000);
  }

  $("#engage").addEventListener("click", engage);
  $("#approve").addEventListener("click", approve);
  $("#copy-host").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("#host-msg").value);
      toast("Message copied");
    } catch {
      toast("Copy failed. Select the text and copy it manually.", true);
    }
  });
  boot();
})();
