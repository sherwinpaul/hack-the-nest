/* Trip Guardian dashboard — vanilla JS, no build step. */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const NS = "http://www.w3.org/2000/svg";
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const ICON = {
    shield: '<path d="M12 2.5 4 5.5v6c0 5 3.4 8.9 8 10 4.6-1.1 8-5 8-10v-6l-8-3Z"/>',
    cloud: '<path d="M17.5 19H8a6 6 0 1 1 5.7-8h1.3a4.5 4.5 0 0 1 2.5 8.2"/><path d="m11 13-2 4h4l-2 4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    plane: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
    scale: '<path d="M3 20h18"/><path d="M6 20V10m6 10V4m6 16v-7"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7"/>',
  };
  const svgIcon = (k) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;

  const STEPS = [
    { key: "orchestrator", name: "Trip Guardian", icon: "shield", color: "#2563eb" },
    { key: "weather", name: "Weather risk", icon: "cloud", color: "#0ea5e9", tool: "weather_risk" },
    { key: "intel", name: "Web intel", icon: "search", color: "#6d4fd8", tool: "web_intel" },
    { key: "fares", name: "Fare search", icon: "plane", color: "#0d9488", tool: "fare_search" },
    { key: "scoring", name: "Scoring", icon: "scale", color: "#475467", tool: "rank_options", model: "Deterministic code" },
    { key: "comms", name: "Host message", icon: "mail", color: "#db2777", tool: "draft_host_message" },
  ];
  const AGENT_COLOR = {
    "Trip Guardian": "#2563eb", "Weather Risk": "#0ea5e9", "Web Intel": "#6d4fd8",
    "Fare Search": "#0d9488", Comms: "#db2777", "Key pool": "#d97706", MCP: "#6d4fd8",
  };
  const TOOL_STEP = Object.fromEntries(STEPS.filter((s) => s.tool).map((s) => [s.tool, s.key]));

  let state = null;
  let selectedId = null;
  let running = false;

  // ---------- formatting ----------
  const usd = (n) => "$" + Math.round(n).toLocaleString("en-US");
  const pct = (p) => `${Math.round(p * 100)}%`;
  const pColor = (p) => (p >= 0.8 ? "var(--green)" : p >= 0.6 ? "var(--amber)" : "var(--red)");
  const rColor = (r) => (r >= 0.5 ? "var(--red)" : r >= 0.2 ? "var(--amber)" : "var(--green)");
  function local(iso, code, withDay = true) {
    const tz = state?.tz?.[code];
    const opts = { hour: "numeric", minute: "2-digit", timeZone: tz || "UTC", timeZoneName: "short" };
    if (withDay) opts.weekday = "short";
    try { return new Intl.DateTimeFormat("en-US", opts).format(new Date(iso)); }
    catch { return new Date(iso).toISOString().slice(11, 16) + " UTC"; }
  }
  function span(ms) {
    const m = Math.max(0, Math.round(ms / 60000));
    const d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mm = m % 60;
    return d ? `${d}d ${h}h` : h ? `${h}h ${mm}m` : `${mm}m`;
  }
  const flightNo = (o) => o.legs[0].flight_no || o.legs[0].carrier;
  const via = (o) => (o.legs.length > 1 ? `via ${o.airports.slice(1, -1).join(", ")}` : "Nonstop");
  const carrierColor = (c) => {
    const palette = ["#2563eb", "#0d9488", "#7c3aed", "#db2777", "#ea580c", "#0891b2", "#4f46e5", "#16a34a"];
    let h = 0; for (const ch of c || "?") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  };

  // ---------- data helpers ----------
  const pick = () => state.ranking[0];
  const current = () => state.ranking.find((r) => r.option.id === state.current_trip.id);
  const byId = (id) => state.ranking.find((r) => r.option.id === id);

  // ---------- render: header + hero ----------
  function renderHeader() {
    const live = state.mode === "live";
    $("#env").classList.toggle("live", live);
    $("#env-label").textContent = live ? "Live data" : "Replay · sample scenario";
    const c = state.commitment;
    $("#c-title").textContent = c.title;
    $("#c-where").textContent = `${c.city} · ${c.airport}`;
    $("#c-deadline").textContent = local(c.must_arrive_by, c.airport);
    $("#c-stake").textContent = usd(c.meeting_value_usd);
    $("#c-budget").textContent = `up to ${usd(c.max_extra_spend_usd)}`;
    tick();
  }
  function tick() {
    if (!state) return;
    const ms = new Date(state.commitment.must_arrive_by) - Date.now();
    $("#c-countdown").textContent = ms > 0 ? span(ms) : "Passed";
  }

  function renderReco() {
    const p = pick(), cur = current();
    if (!p) return;
    const o = p.option;
    const isCurrent = o.id === state.current_trip.id;
    $("#reco-title").textContent = isCurrent ? "Keep your current booking" : `Switch to ${flightNo(o)} ${via(o).toLowerCase() === "nonstop" ? "nonstop" : via(o)}`;
    const slack = new Date(state.commitment.must_arrive_by) - new Date(o.arrive);
    $("#reco-sub").textContent = `Lands ${local(o.arrive, o.airports.at(-1))} · ${span(slack)} before your deadline · ${usd(o.price_usd)}`;
    $("#reco-source").textContent = o.source === "kiwi" ? "Live fare from Kiwi.com" : state.mode === "replay" ? "Sample fare" : `Fare via ${o.source}`;
    const curP = cur ? cur.p_on_time : 0;
    $("#cmp-cur-val").textContent = pct(curP);
    $("#cmp-pick-val").textContent = pct(p.p_on_time);
    requestAnimationFrame(() => {
      $("#cmp-cur").style.width = pct(curP);
      $("#cmp-cur").style.background = pColor(curP);
      $("#cmp-pick").style.width = pct(p.p_on_time);
    });
    $("#m-extra").textContent = p.extra_cost_usd ? `+${usd(p.extra_cost_usd)}` : "No extra";
    $("#m-saved").textContent = cur ? usd(Math.max(0, cur.expected_loss_usd - p.expected_loss_usd)) : "—";
    const avoided = (cur?.option.airports || [])
      .filter((a) => !o.airports.includes(a))
      .map((a) => [a, state.risks[a]?.disruption_prob ?? 0])
      .sort((a, b) => b[1] - a[1])[0];
    $("#m-avoid").textContent = avoided ? `${avoided[0]} · ${pct(avoided[1])}` : "None needed";
    const btn = $("#reco-book");
    btn.disabled = isCurrent;
    btn.textContent = isCurrent ? "Already booked" : "Review & book";
  }

  // ---------- pipeline ----------
  function renderPipeline() {
    const routing = state.routing || {};
    $("#pipeline").innerHTML = STEPS.map((s) => {
      const model = s.model || (routing[s.key] || "").split(":").slice(1).join(":") || "";
      return `<li class="step" id="step-${s.key}">
        <span class="step-icon" data-icon="${s.icon}">${svgIcon(s.icon)}</span>
        <span class="step-name">${esc(s.name)}</span>
        <span class="step-meta">${esc(model)}</span>
      </li>`;
    }).join("");
  }
  function setStep(key, status) {
    const el = $(`#step-${key}`);
    if (!el) return;
    el.classList.remove("running", "done");
    if (status) el.classList.add(status);
    const icon = el.querySelector(".step-icon");
    icon.innerHTML = svgIcon(status === "done" ? "check" : icon.dataset.icon);
  }
  function setRunStatus(text, cls) {
    const el = $("#run-status");
    el.textContent = text;
    el.className = `status-chip ${cls || ""}`;
  }

  // ---------- map ----------
  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  function projector(W, H, pad) {
    const pts = Object.values(state.coords).filter(Boolean);
    const lats = pts.map((p) => p[0]), lons = pts.map((p) => p[1]);
    const minLat = Math.min(...lats) - 0.8, maxLat = Math.max(...lats) + 1.4;
    const minLon = Math.min(...lons) - 1.6, maxLon = Math.max(...lons) + 1.6;
    const k = Math.cos(((minLat + maxLat) / 2) * Math.PI / 180);
    const s = Math.min((W - pad * 2) / ((maxLon - minLon) * k), (H - pad * 2) / (maxLat - minLat));
    const ox = (W - (maxLon - minLon) * k * s) / 2, oy = (H - (maxLat - minLat) * s) / 2;
    return ([lat, lon]) => [ox + (lon - minLon) * k * s, oy + (maxLat - lat) * s];
  }
  function curve(a, b, bend) {
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    return `Q ${(mx - dy * bend).toFixed(1)} ${(my + dx * bend).toFixed(1)} ${b[0].toFixed(1)} ${b[1].toFixed(1)}`;
  }
  function renderMap() {
    const svg = $("#map");
    svg.innerHTML = "";
    const W = 800, H = 420;
    const P = projector(W, H, 56);
    const defs = el("defs", {}, svg);
    const g = el("radialGradient", { id: "riskGrad" }, defs);
    el("stop", { offset: "0%", "stop-color": "#dc3545", "stop-opacity": "0.28" }, g);
    el("stop", { offset: "100%", "stop-color": "#dc3545", "stop-opacity": "0" }, g);
    const ga = el("radialGradient", { id: "warnGrad" }, defs);
    el("stop", { offset: "0%", "stop-color": "#d97706", "stop-opacity": "0.22" }, ga);
    el("stop", { offset: "100%", "stop-color": "#d97706", "stop-opacity": "0" }, ga);
    const pat = el("pattern", { id: "dots", width: 16, height: 16, patternUnits: "userSpaceOnUse" }, defs);
    el("circle", { cx: 2, cy: 2, r: 1, class: "dot" }, pat);
    el("rect", { x: 0, y: 0, width: W, height: H, fill: "url(#dots)" }, svg);

    for (const [code, r] of Object.entries(state.risks)) {
      const c = state.coords[code];
      if (!c || r.disruption_prob < 0.2) continue;
      const [x, y] = P(c);
      el("circle", { cx: x, cy: y, r: 30 + 110 * r.disruption_prob, fill: r.disruption_prob >= 0.5 ? "url(#riskGrad)" : "url(#warnGrad)", class: "halo" }, svg);
    }

    const pid = pick()?.option.id, cid = state.current_trip.id;
    const visible = state.ranking.slice(0, 8);
    if (!visible.some((r) => r.option.id === cid) && current()) visible.push(current());
    const order = [...visible].sort((a, b) => w(a) - w(b));
    function w(r) { return r.option.id === pid ? 2 : r.option.id === cid ? 1 : 0; }
    order.forEach((r) => {
      const o = r.option;
      if (o.airports.some((a) => !state.coords[a])) return;
      const idx = state.ranking.indexOf(r);
      const bend = o.id === pid ? -0.18 : (idx % 2 ? -1 : 1) * (0.07 + 0.04 * Math.floor(idx / 2));
      let d = "";
      o.legs.forEach((leg, i) => {
        const a = P(state.coords[leg.origin]), b = P(state.coords[leg.destination]);
        if (i === 0) d += `M ${a[0].toFixed(1)} ${a[1].toFixed(1)} `;
        d += curve(a, b, bend) + " ";
      });
      const cls = o.id === pid ? "pick" : o.id === cid ? "cur" : "alt";
      if (cls === "pick") el("path", { d, class: "route pick-glow" }, svg);
      el("path", { d, class: `route ${cls}`, id: `r-${o.id}`, "data-id": o.id }, svg);
    });

    if (pid && $(`#r-${CSS.escape(pid)}`)) {
      const plane = el("path", { d: "M-8 -1.6 L5 -1.6 L9 0 L5 1.6 L-8 1.6 Z M-1 -1.6 L-5 -7.5 L-2.5 -7.5 L4 -1.6 Z M-1 1.6 L-5 7.5 L-2.5 7.5 L4 1.6 Z M-8 -1.6 L-10 -4.5 L-8.5 -4.5 L-6 -1.6 Z M-8 1.6 L-10 4.5 L-8.5 4.5 L-6 1.6 Z", class: "plane" }, svg);
      const m = el("animateMotion", { dur: "6s", repeatCount: "indefinite", rotate: "auto" }, plane);
      el("mpath", { href: `#r-${pid}` }, m);
    }

    for (const [code, c] of Object.entries(state.coords)) {
      if (!c) continue;
      const [x, y] = P(c);
      const risk = state.risks[code]?.disruption_prob ?? 0;
      el("circle", { cx: x, cy: y, r: 6, class: "ap-ring", stroke: rColor(risk) }, svg);
      el("circle", { cx: x, cy: y, r: 2.2, fill: rColor(risk) }, svg);
      const label = el("g", { class: "ap-label", transform: `translate(${x}, ${y - 30})` }, svg);
      const rect = el("rect", { x: -41, y: -13, width: 82, height: 26, rx: 8 }, label);
      rect.style.filter = "drop-shadow(0 1px 2px rgba(16,24,40,.08))";
      const t = el("text", { x: -31, y: 4.5 }, label);
      t.textContent = code;
      const rt = el("text", { x: 31, y: 4.5, "text-anchor": "end", class: "risk", fill: rColor(risk) }, label);
      rt.textContent = pct(risk);
    }
  }
  function highlight(id) {
    document.querySelectorAll("#map .route:not(.pick-glow)").forEach((p) => {
      p.classList.toggle("hl", !!id && p.dataset.id === id && !p.classList.contains("pick"));
      p.classList.toggle("dim", !!id && p.dataset.id !== id);
    });
  }

  // ---------- airport conditions ----------
  function renderRisks() {
    const items = Object.entries(state.risks).sort((a, b) => b[1].disruption_prob - a[1].disruption_prob);
    $("#risk-note").textContent = state.mode === "live" ? "Open-Meteo forecast" : "Recorded scenario";
    $("#risk-list").innerHTML = items.map(([code, r]) => `
      <li class="risk-item">
        <span class="risk-code">${esc(code)}</span>
        <span class="risk-why">${esc(r.reason.replace(/^\[sample\]\s*/, ""))}
          <span class="rb"><i style="width:${pct(r.disruption_prob)};background:${rColor(r.disruption_prob)}"></i></span>
        </span>
        <span class="risk-pct" style="color:${rColor(r.disruption_prob)}">${pct(r.disruption_prob)}</span>
      </li>`).join("");
  }

  // ---------- options table ----------
  function statusPill(r, i) {
    if (r.p_on_time === 0) return '<span class="pill pill-gray">Too late</span>';
    if (i === 0) return '<span class="pill pill-blue">Recommended</span>';
    if (r.option.id === state.current_trip.id) return '<span class="pill pill-red">Booked</span>';
    return r.p_on_time >= 0.8 ? '<span class="pill pill-green">Reliable</span>' : '<span class="pill pill-amber">At risk</span>';
  }
  function renderOptions() {
    const rows = state.ranking.slice(0, 8);
    if (!rows.some((r) => r.option.id === state.current_trip.id) && current()) rows.push(current());
    $("#options-body").innerHTML = rows.map((r) => {
      const o = r.option, i = state.ranking.indexOf(r);
      const carrier = o.legs[0].carrier;
      return `<tr data-id="${esc(o.id)}" class="${o.id === selectedId ? "selected" : ""}">
        <td><span class="flight"><span class="carrier" style="background:${carrierColor(carrier)}">${esc(carrier)}</span>
          <span><b>${esc(flightNo(o))}</b><span class="sub">${esc(o.legs.length > 1 ? o.legs.map((l) => l.flight_no).slice(1).join(", ") : o.source === "kiwi" && state.mode === "live" ? "Kiwi.com" : "")}</span></span></span></td>
        <td>${esc(o.airports.join(" → "))}<span class="sub">${esc(via(o))}</span></td>
        <td>${esc(local(o.legs[0].depart, o.airports[0], false))}</td>
        <td>${esc(local(o.arrive, o.airports.at(-1), false))}</td>
        <td><span class="ontime"><span class="bar"><i data-w="${pct(r.p_on_time)}" style="background:${pColor(r.p_on_time)}"></i></span><span>${pct(r.p_on_time)}</span></span></td>
        <td class="num">${usd(o.price_usd)}<span class="sub">${r.extra_cost_usd ? "+" + usd(r.extra_cost_usd) : "no extra"}</span></td>
        <td class="num"><b>${usd(r.expected_loss_usd)}</b></td>
        <td>${statusPill(r, i)}</td>
      </tr>`;
    }).join("");
    requestAnimationFrame(() => document.querySelectorAll(".ontime i").forEach((b) => (b.style.width = b.dataset.w)));
    document.querySelectorAll("#options-body tr").forEach((tr) => {
      tr.addEventListener("click", () => select(tr.dataset.id));
      tr.addEventListener("mouseenter", () => highlight(tr.dataset.id));
      tr.addEventListener("mouseleave", () => highlight(null));
    });
    updateSelection();
  }
  function select(id) {
    selectedId = id;
    document.querySelectorAll("#options-body tr").forEach((tr) => tr.classList.toggle("selected", tr.dataset.id === id));
    updateSelection();
  }
  function updateSelection() {
    const r = byId(selectedId);
    const btn = $("#approve");
    if (!r) { $("#selected-label").textContent = "Select an option"; btn.disabled = true; return; }
    const isCurrent = r.option.id === state.current_trip.id;
    $("#selected-label").innerHTML = `<b>${esc(flightNo(r.option))}</b> · ${esc(r.option.airports.join(" → "))} · ${pct(r.p_on_time)} on time · ${usd(r.option.price_usd)}`;
    btn.disabled = isCurrent || r.p_on_time === 0;
    btn.textContent = isCurrent ? "Already booked" : r.option.source === "kiwi" ? "Book on Kiwi.com" : "Book selected";
  }

  // ---------- booking ----------
  function openConfirm(id) {
    const r = byId(id);
    if (!r) return;
    const o = r.option;
    $("#confirm-title").textContent = `${flightNo(o)} · ${o.airports.join(" → ")}`;
    const how = o.source === "kiwi"
      ? "You'll finish the purchase on Kiwi.com. Trip Guardian never takes payment."
      : state.mode === "replay" ? "Replay mode: this booking is simulated." : "Duffel test mode only.";
    $("#confirm-body").textContent = `${usd(o.price_usd)}, lands ${local(o.arrive, o.airports.at(-1))} with a ${pct(r.p_on_time)} chance of arriving on time. ${how}`;
    $("#confirm-ok").textContent = o.source === "kiwi" ? "Continue to Kiwi.com" : "Confirm booking";
    const dlg = $("#confirm");
    dlg.returnValue = "";
    dlg.showModal();
    dlg.addEventListener("close", async function onClose() {
      dlg.removeEventListener("close", onClose);
      if (dlg.returnValue !== "ok") return;
      try {
        const res = await fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ option_id: o.id }) });
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail || res.statusText);
        const link = /^https:\/\//.test(body.url || "") ? ` <a href="${esc(body.url)}" target="_blank" rel="noopener noreferrer">Open Kiwi.com ↗</a>` : "";
        toast(`${esc(body.message)}${link}`, false, true);
      } catch (e) {
        toast(`Booking failed: ${esc(e.message)}`, true, true);
      }
    });
  }
  function toast(html, err = false, isHtml = false) {
    const t = $("#toast");
    t[isHtml ? "innerHTML" : "textContent"] = html;
    t.classList.toggle("err", err);
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), 8000);
  }

  // ---------- activity + run ----------
  let t0 = 0, count = 0;
  function act(type, agent, html) {
    const list = $("#activity");
    list.querySelector(".empty")?.remove();
    const li = document.createElement("li");
    li.className = `act ${type}`;
    li.style.setProperty("--c", AGENT_COLOR[agent] || "var(--ink-3)");
    li.innerHTML = `<span class="dot"></span><div><span class="who">${esc(agent)}</span> <span class="what">${html}</span></div><span class="t">${((performance.now() - t0) / 1000).toFixed(1)}s</span>`;
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
    $("#activity-count").textContent = `${++count} events`;
  }
  const pretty = (s) => { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s; } };
  const more = (label, body) => (body && body !== "{}" ? `<details><summary>${esc(label)}</summary><pre>${esc(pretty(body))}</pre></details>` : "");

  function addSources(query, items) {
    const box = $("#evidence");
    box.querySelector(".empty")?.remove();
    const safe = (u) => (/^https?:\/\//i.test(u) ? u : "#");
    box.insertAdjacentHTML("beforeend",
      (query ? `<div class="ev-query">${svgIcon("search")}<span>Exa search: <b>${esc(query)}</b></span></div>` : "") +
      items.map((s, i) => `<a class="ev-card" href="${esc(safe(s.url))}" target="_blank" rel="noopener noreferrer" style="animation-delay:${i * 50}ms">
        <span class="ev-top"><span class="ev-fav">${esc((s.domain || "?")[0])}</span><span class="ev-domain">${esc(s.domain)}</span><span class="ev-date">${esc(s.published || "")}</span></span>
        <span class="ev-title">${esc(s.title)}</span></a>`).join(""));
  }

  function handle(ev) {
    switch (ev.type) {
      case "agent":
        if (ev.agent === "Trip Guardian") setStep("orchestrator", "running");
        break;
      case "tool_called": {
        const step = TOOL_STEP[ev.tool];
        if (step && ev.agent === "Trip Guardian") setStep(step, "running");
        act("call", ev.agent, `called <code>${esc(ev.tool)}</code>${more("Arguments", ev.args)}`);
        break;
      }
      case "tool_output": {
        const step = TOOL_STEP[ev.tool];
        if (step && ev.agent === "Trip Guardian") setStep(step, "done");
        if (ev.tool === "draft_host_message") { $("#host-msg").value = ev.output; $("#copy-host").disabled = false; }
        act("result", ev.agent, `got result from <code>${esc(ev.tool)}</code>${more("Output", ev.output)}`);
        break;
      }
      case "system": act("warn", ev.agent, esc(ev.text)); break;
      case "sources": addSources(ev.query, ev.items); break;
      case "error": act("error", "Error", esc(ev.text)); break;
      case "final":
        setStep("orchestrator", "done");
        $("#brief").innerHTML = DOMPurify.sanitize(marked.parse(ev.text || ""));
        act("result", "Trip Guardian", "recommendation ready, waiting for your approval");
        break;
    }
  }

  function run() {
    if (running) return;
    running = true; t0 = performance.now(); count = 0;
    $("#activity").innerHTML = "";
    $("#evidence").innerHTML = '<p class="empty">Waiting for the Web Intel agent…</p>';
    $("#brief").innerHTML = '<p class="empty">Agents are working…</p>';
    STEPS.forEach((s) => setStep(s.key, null));
    setRunStatus("Running", "running");
    const btn = $("#engage");
    btn.disabled = true; btn.classList.add("running");
    $("#engage-label").textContent = "Running…";

    const es = new EventSource("/api/run");
    let failed = false;
    const finish = async (ok) => {
      es.close(); // EventSource auto-reconnects, which would start a second run
      running = false;
      btn.disabled = false; btn.classList.remove("running");
      $("#engage-label").textContent = "Run again";
      setRunStatus(ok ? "Complete" : "Failed", ok ? "done" : "failed");
      if (!ok && !$("#brief").querySelector("h1,h2,h3,ul,p:not(.empty)")) {
        $("#brief").innerHTML = '<p class="empty">The run stopped before a recommendation. The activity log has details.</p>';
      }
      if (ok) await refresh(); // live fares may have been re-fetched during the run
    };
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "done") return finish(!failed);
      if (ev.type === "error") failed = true;
      handle(ev);
    };
    es.onerror = () => { if (running) { act("error", "Error", "Lost connection to the server."); finish(false); } };
  }

  // ---------- boot ----------
  function renderAll() {
    renderHeader(); renderReco(); renderMap(); renderRisks(); renderOptions();
  }
  async function refresh() {
    const res = await fetch("/api/state");
    if (!res.ok) throw new Error(res.statusText);
    state = await res.json();
    if (!byId(selectedId)) selectedId = pick()?.option.id ?? null;
    renderAll();
  }
  async function boot() {
    try { await refresh(); } catch (e) { toast(`Could not load data: ${e.message}`, true); return; }
    renderPipeline();
    setInterval(tick, 30000);
  }

  $("#engage").addEventListener("click", run);
  $("#approve").addEventListener("click", () => openConfirm(selectedId));
  $("#reco-book").addEventListener("click", () => openConfirm(pick()?.option.id));
  $("#copy-host").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#host-msg").value); toast("Message copied"); }
    catch { toast("Copy failed. Select the text and copy it manually.", true); }
  });
  boot();
})();
