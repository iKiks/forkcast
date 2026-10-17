/* Forkcast broadcast client. Plain JS, no build step.
 *
 * The server streams a steady match clock: 5 Hz tracking frames ("track"), events, agent traces,
 * cues, outlooks and stats, each stamped with T (monotonic match seconds). The client keeps a
 * playback clock, interpolates between tracking frames and releases every message when the
 * picture reaches its T, so overlays land exactly on the moment they describe.
 */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const L = 105, W = 68, MARGIN = 3.5;
  const AGENT_COLORS = {
    Spotter: "#7dd3fc", Analyst: "#c4b5fd", Simulator: "#c6f432", Narrator: "#fdba74",
    Skeptic: "#f87171", Director: "#fcd34d", Localizer: "#86efac",
  };
  const VOICE_LANG = { en: "en-GB", fr: "fr-FR", es: "es-ES", pt: "pt-BR", pcm: "en-NG" };
  const LANG_NAMES = { en: "English", fr: "Français", es: "Español", pt: "Português", pcm: "Naijá (Pidgin)" };
  const KIND_LABEL = {
    goal: "GOAL", chance: "BIG CHANCE", turnover: "TURNOVER", red: "RED CARD", halftime: "HALF TIME",
    fulltime: "FULL TIME", control_take: "CONTROL", control_chaos: "CHAOS", forecast: "MATCH OUTLOOK",
    record_shot: "FASTEST SHOT", record_sprint: "TOP SPEED", record_pass: "HARDEST PASS", record_distance: "MOST DISTANCE",
  };
  const ON_BALL = ["pass", "carry", "cross", "shot"];
  const SPEED_TAG_KMH = 30;

  const S = {
    clubs: [], meta: null, es: null, sid: null, paused: false, speed: 15, lens: "casual", lang: "en", voice: false,
    players: new Map(), slots: [], on: [],
    fT: [], fBall: [], fPos: [], playT: 0, started: false, endReceived: false, endT: Infinity,
    queue: [], score: [0, 0], lastOnBall: null, events: [], river: [], cues: [], recap: null,
    lab: null, arrows: [], flash: -1e9, outlook: null, lastStats: null, speedTags: new Map(), waitSince: 0,
  };

  // ------------------------------------------------------------------ setup
  async function init() {
    const res = await fetch("/api/clubs").then((r) => r.json());
    S.clubs = res.clubs;
    $("league").textContent = `${res.league} · fictional & synthetic`;
    for (const sel of [$("home"), $("away")]) sel.innerHTML = S.clubs.map((c) => `<option value="${c.id}">${c.name}</option>`).join("");
    $("home").value = "kes"; $("away").value = "amb";
    $("lang").innerHTML = Object.entries(LANG_NAMES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    $("agentsKey").innerHTML = Object.entries(AGENT_COLORS).map(([k, c]) => `<span class="chip" style="background:${c}">${k}</span>`).join("");
    $("kick").onclick = start;
    $("pause").onclick = () => setPaused(!S.paused);
    $("speed").onchange = (e) => { S.speed = +e.target.value; control({ speed: S.speed }); };
    $("lens").onchange = (e) => { S.lens = e.target.value; renderForecast(); renderPlayerCard(); };
    $("lang").onchange = (e) => { S.lang = e.target.value; renderForecast(); };
    $("voice").onclick = () => {
      S.voice = !S.voice; $("voice").setAttribute("aria-pressed", S.voice); $("voice").textContent = S.voice ? "Voice on" : "Voice off";
      if (!S.voice && "speechSynthesis" in window) speechSynthesis.cancel();
    };
    document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
    $("labPlay").onclick = labFreeze;
    $("labDuel").onclick = labDuel;
    $("labResume").onclick = labResume;
    $("recapClose").onclick = () => $("recap").hidden = true;
    $("dlCues").onclick = () => download("overlay-cues.json", S.cues);
    $("dlRecap").onclick = () => download("recap.json", S.recap);
    pitch.addEventListener("click", onPitchClick);
    river.addEventListener("mousemove", onRiverHover);
    river.addEventListener("mouseleave", () => $("riverTip").hidden = true);
    window.addEventListener("resize", resize);
    if ("ResizeObserver" in window) { const ro = new ResizeObserver(() => resize()); ro.observe($("broadcast")); ro.observe(river.parentElement); }
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.code === "Space") { e.preventDefault(); setPaused(!S.paused); }
      if (e.key === "p") labFreeze();
    });
    resize();
    requestAnimationFrame(frame);
    start();
  }

  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    for (const t of ["forecast", "news", "lab", "stats"]) $(`tab-${t}`).hidden = t !== name;
  }
  function control(body) {
    if (!S.sid) return Promise.resolve();
    return fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session: S.sid, ...body }) }).catch(() => {});
  }
  function setPaused(p) { S.paused = p; $("pause").textContent = p ? "Resume" : "Pause"; control({ paused: p }); }

  function start() {
    if (S.es) S.es.close();
    Object.assign(S, {
      players: new Map(), slots: [], on: [], fT: [], fBall: [], fPos: [], playT: 0, started: false, endReceived: false,
      endT: Infinity, queue: [], score: [0, 0], lastOnBall: null, events: [], river: [], cues: [], recap: null, lab: null,
      arrows: [], outlook: null, lastStats: null, speedTags: new Map(), paused: false, flash: -1e9,
    });
    $("pause").textContent = "Pause";
    for (const id of ["trace", "overlays", "labOut", "forkOut"]) $(id).innerHTML = "";
    $("meter").hidden = true; $("labHint").hidden = true; $("broadcast").classList.remove("lab"); $("recap").hidden = true;
    groups.clear();
    const q = new URLSearchParams({ home: $("home").value, away: $("away").value, seed: $("seed").value, speed: $("speed").value, skip: $("skip").value || 0 });
    S.speed = +$("speed").value;
    S.es = new EventSource(`/api/live?${q}`);
    S.es.onmessage = (m) => receive(JSON.parse(m.data));
    S.es.onerror = () => { if (S.endReceived) S.es.close(); };
  }

  // ------------------------------------------------------------------ stream: receive now, release on time
  function receive(msg) {
    if (msg.type === "meta") return onMeta(msg);
    if (msg.type === "track") return onTrack(msg);
    if (msg.type === "end") { S.endReceived = true; S.endT = msg.T; }
    if (msg.catchup || !S.started || msg.T == null) return apply(msg);
    S.queue.push(msg);
  }
  function apply(msg) {
    switch (msg.type) {
      case "event": return onEvent(msg);
      case "trace": return onTrace(msg);
      case "cue": return onCue(msg);
      case "outlook": return onOutlook(msg);
      case "stats": return onStats(msg);
      case "recap": return onRecap(msg);
      case "end": S.es && S.es.close(); return;
    }
  }
  function releaseUntil(T) {
    let k = 0;
    while (k < S.queue.length && S.queue[k].T <= T) k++;
    if (!k) return;
    const due = S.queue.splice(0, k);
    for (const m of due) apply(m);
  }

  function onMeta(m) {
    S.meta = m; S.sid = m.session;
    const [h, a] = [m.home, m.away];
    document.documentElement.style.setProperty("--home", h.color);
    document.documentElement.style.setProperty("--away", a.color);
    $("bugHome").textContent = h.short; $("bugHome").style.background = h.color;
    $("bugAway").textContent = a.short; $("bugAway").style.background = a.color;
    for (const [bar, c] of [["olH", h.color], ["olA", a.color], ["fcH", h.color], ["fcA", a.color]]) $(bar).style.background = c;
    $("riverLegend").innerHTML = `<span><i style="background:${h.color}"></i>${h.short} win</span><span><i style="background:var(--draw)"></i>draw</span><span><i style="background:${a.color}"></i>${a.short} win</span>`;
    const lens = [["casual", "Casual fan"], ["analyst", "Analyst"], [`club:${h.id}`, `${h.name} fan`], [`club:${a.id}`, `${a.name} fan`]];
    for (const [ti, club] of [[0, h], [1, a]]) {
      for (const p of club.players.concat(club.bench)) S.players.set(p.id, { ...p, team: ti });
      for (const p of club.players) lens.push([`player:${p.id}`, `Player focus: ${p.name} (${club.short})`]);
    }
    $("lens").innerHTML = lens.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
    if (lens.some(([v]) => v === S.lens)) $("lens").value = S.lens; else S.lens = "casual";
    S.slots = m.slots.slice(); S.on = new Array(22).fill(1);
    S.outlook = { ...m.prematch, story: m.prematch_story, clock: "Pre-match", T: 0, score: [0, 0] };
    S.river = [{ T: 0, h: m.prematch.home_win, d: m.prematch.draw, a: m.prematch.away_win }];
    renderOutlook(); renderForecast();
    updateTape({ cues_aired: 0, rejected: 0, held: 0, latency_p50_ms: 0, latency_p99_ms: 0, forks_run: 0, model: m.model });
  }

  function onTrack(c) {
    for (let i = 0; i < c.T.length; i++) { S.fT.push(c.T[i]); S.fBall.push(c.ball[i]); S.fPos.push(c.pos[i]); }
    S.pendingSlots = { slots: c.slots, on: c.on, T: c.T[c.T.length - 1] };
    if (!S.started) { S.started = true; S.playT = c.T[0]; }
  }

  // ------------------------------------------------------------------ events
  function onEvent(ev) {
    ev.type = ev.type_;
    S.events.push(ev);
    const st = ev.state;
    if (st.score[0] !== S.score[0] || st.score[1] !== S.score[1]) { S.flash = performance.now(); vibrate([180, 80, 180]); }
    S.score = st.score;
    $("bugScore").textContent = `${st.score[0]}–${st.score[1]}`;
    $("bugClock").textContent = ev.clock;
    if (["pass", "carry", "cross"].includes(ev.type)) S.lastOnBall = ev;  // Play the Moment replays passes, carries and crosses
  }

  // ------------------------------------------------------------------ canvas
  const pitch = $("pitch"), ctx = pitch.getContext("2d");
  const river = $("river"), rctx = river.getContext("2d");
  let view = { s: 8, ox: 0, oy: 0 };
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    for (const c of [pitch, river]) {
      const r = c.getBoundingClientRect();
      c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr);
      c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    const r = pitch.getBoundingClientRect();
    const s = Math.min(r.width / (L + 2 * MARGIN), r.height / (W + 2 * MARGIN));
    view = { s, ox: (r.width - L * s) / 2, oy: (r.height - W * s) / 2 };
    drawRiver();
  }
  const X = (x) => view.ox + x * view.s, Y = (y) => view.oy + y * view.s;

  function drawPitch() {
    const r = pitch.getBoundingClientRect();
    ctx.clearRect(0, 0, r.width, r.height);
    const s = view.s;
    for (let i = 0; i < 14; i++) {
      ctx.fillStyle = i % 2 ? "#18693b" : "#1b7442";
      ctx.fillRect(X(i * L / 14), Y(0), L / 14 * s + 0.5, W * s);
    }
    const vg = ctx.createRadialGradient(X(L / 2), Y(W / 2), 10, X(L / 2), Y(W / 2), L * s * 0.7);
    vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(0,0,0,.3)");
    ctx.fillStyle = vg; ctx.fillRect(X(0), Y(0), L * s, W * s);
    ctx.strokeStyle = "rgba(255,255,255,.82)"; ctx.lineWidth = Math.max(1.2, s * 0.12);
    ctx.strokeRect(X(0), Y(0), L * s, W * s);
    line(L / 2, 0, L / 2, W);
    circle(L / 2, W / 2, 9.15, false); circle(L / 2, W / 2, 0.35, true);
    for (const side of [0, 1]) {
      const x0 = side ? L - 16.5 : 0, x1 = side ? L - 5.5 : 0;
      ctx.strokeRect(X(x0), Y(W / 2 - 20.16), 16.5 * s, 40.32 * s);
      ctx.strokeRect(X(x1), Y(W / 2 - 9.16), 5.5 * s, 18.32 * s);
      circle(side ? L - 11 : 11, W / 2, 0.3, true);
      ctx.beginPath();
      const cx = side ? L - 11 : 11, a = Math.acos(5.5 / 9.15);
      if (side) ctx.arc(X(cx), Y(W / 2), 9.15 * s, Math.PI - a, Math.PI + a); else ctx.arc(X(cx), Y(W / 2), 9.15 * s, -a, a);
      ctx.stroke();
      ctx.fillStyle = "rgba(255,255,255,.9)";
      ctx.fillRect(side ? X(L) : X(-1.2), Y(W / 2 - 3.66), 1.2 * s, 7.32 * s);
    }
  }
  function line(a, b, c, d) { ctx.beginPath(); ctx.moveTo(X(a), Y(b)); ctx.lineTo(X(c), Y(d)); ctx.stroke(); }
  function circle(x, y, r, fill) {
    ctx.beginPath(); ctx.arc(X(x), Y(y), r * view.s, 0, Math.PI * 2);
    if (fill) { ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.fill(); } else ctx.stroke();
  }

  // ------------------------------------------------------------------ playback
  function frameIndex(T) {
    const a = S.fT; let lo = 0, hi = a.length - 1;
    if (hi < 0) return -1;
    if (T <= a[0]) return 0;
    if (T >= a[hi]) return hi;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (a[mid] <= T) lo = mid; else hi = mid; }
    return lo;
  }
  function sample(T) {
    const i = frameIndex(T);
    if (i < 0) return null;
    const j = Math.min(i + 1, S.fT.length - 1);
    const span = S.fT[j] - S.fT[i];
    const u = span > 0 ? Math.min(1, Math.max(0, (T - S.fT[i]) / span)) : 0;
    const b0 = S.fBall[i], b1 = S.fBall[j], p0 = S.fPos[i], p1 = S.fPos[j];
    const ball = [b0[0] + (b1[0] - b0[0]) * u, b0[1] + (b1[1] - b0[1]) * u, b0[2] + (b1[2] - b0[2]) * u];
    const pos = new Array(44);
    for (let k = 0; k < 44; k++) pos[k] = p0[k] + (p1[k] - p0[k]) * u;
    // speed from the surrounding frames (km/h)
    const pa = S.fPos[Math.max(0, i - 1)], pb = S.fPos[j];
    const dt = Math.max(0.2, S.fT[j] - S.fT[Math.max(0, i - 1)]);
    const spd = new Array(22);
    for (let s = 0; s < 22; s++) spd[s] = Math.hypot(pb[2 * s] - pa[2 * s], pb[2 * s + 1] - pa[2 * s + 1]) / dt * 3.6;
    return { ball, pos, spd, i };
  }

  let lastFrame = performance.now();
  function frame(now) {
    const dt = Math.min(0.1, (now - lastFrame) / 1000); lastFrame = now;
    if (S.started) {
      const lastT = S.fT[S.fT.length - 1];
      if (!S.paused && !S.lab) S.playT += dt * S.speed;
      if (S.playT > lastT) {
        S.playT = lastT;
        if (!S.endReceived && !S.paused && !S.lab) { S.waitSince = S.waitSince || now; } else S.waitSince = 0;
      } else S.waitSince = 0;
      if (lastT - S.playT > Math.max(4, S.speed * 1.5) && !S.lab) S.playT = lastT - S.speed * 0.4;
      $("buffer").hidden = !(S.waitSince && now - S.waitSince > 1200);
      if (S.pendingSlots && S.pendingSlots.T <= S.playT + 1) { S.slots = S.pendingSlots.slots; S.on = S.pendingSlots.on; S.pendingSlots = null; }
      if (!S.lab) releaseUntil(S.endReceived && S.playT >= lastT - 0.01 ? Infinity : S.playT);
    }
    drawPitch();
    const smp = S.started ? sample(S.playT) : null;
    if (smp) {
      drawTrail();
      drawPlayers(smp, now);
      drawBall(smp.ball);
      drawArrows();
      positionTags(smp);
    }
    requestAnimationFrame(frame);
  }

  function focusId() { return S.lens.startsWith("player:") ? S.lens.slice(7) : null; }

  function drawTrail() {
    const i1 = frameIndex(S.playT), i0 = frameIndex(S.playT - 1.8);
    if (i1 - i0 < 2) return;
    ctx.lineCap = "round";
    for (let k = i0; k < i1; k++) {
      const a = S.fBall[k], b = S.fBall[k + 1];
      const f = (k - i0) / (i1 - i0);
      ctx.strokeStyle = `rgba(255,255,255,${0.05 + 0.35 * f})`;
      ctx.lineWidth = 1 + 2 * f;
      ctx.beginPath(); ctx.moveTo(X(a[0]), Y(a[1])); ctx.lineTo(X(b[0]), Y(b[1])); ctx.stroke();
    }
  }

  function drawPlayers(smp, now) {
    if (!S.meta) return;
    const s = view.s, rad = Math.max(6, 1.2 * s);
    const focus = focusId();
    const cols = [S.meta.home, S.meta.away];
    const [bx, by, bz] = smp.ball;
    let holder = -1, hd = 2.2;
    for (let k = 0; k < 22; k++) {
      if (!S.on[k]) continue;
      const d = Math.hypot(smp.pos[2 * k] - bx, smp.pos[2 * k + 1] - by);
      if (d < hd && bz < 1.5) { hd = d; holder = k; }
    }
    S.holder = holder;
    for (let k = 0; k < 22; k++) {
      if (!S.on[k]) continue;
      const ti = k < 11 ? 0 : 1;
      const pid = S.slots[k], p = S.players.get(pid) || {};
      const gk = k % 11 === 0;
      const x = X(smp.pos[2 * k]), y = Y(smp.pos[2 * k + 1]);
      ctx.beginPath(); ctx.ellipse(x + 1.5, y + rad * 0.55, rad * 1.05, rad * 0.55, 0, 0, Math.PI * 2); ctx.fillStyle = "rgba(0,0,0,.28)"; ctx.fill();
      if (k === holder) { ctx.beginPath(); ctx.arc(x, y, rad + 4, 0, Math.PI * 2); ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 2; ctx.stroke(); }
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fillStyle = gk ? (ti ? "#f5f5f4" : "#e2e8f0") : cols[ti].color; ctx.fill();
      ctx.lineWidth = 2; ctx.strokeStyle = cols[ti].alt_color; ctx.stroke();
      ctx.fillStyle = "#0a0e13";
      ctx.font = `700 ${Math.round(rad * 0.95)}px Archivo, sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(p.number ?? "", x, y + 0.5);
      // player identification: the man on the ball and the focus player carry a name tag
      const showName = k === holder || focus === pid;
      if (showName && p.short) pill(x, y + rad + 13, `${p.short}`, focus === pid ? "#c6f432" : "rgba(9,13,18,.85)", focus === pid ? "#11160a" : "#fff");
      if (focus === pid) { ctx.beginPath(); ctx.arc(x, y, rad + 7 + Math.sin(now / 200) * 1.5, 0, Math.PI * 2); ctx.strokeStyle = "#c6f432"; ctx.lineWidth = 2.5; ctx.stroke(); }
      // speed indicator, triggered when a player passes the threshold
      const v = smp.spd[k];
      const tag = S.speedTags.get(k);
      if (v >= SPEED_TAG_KMH && !S.paused) S.speedTags.set(k, { kmh: Math.max(v, tag && tag.until > now ? tag.kmh : 0), until: now + 1300 });
      const t2 = S.speedTags.get(k);
      if (t2 && t2.until > now) pill(x, y - rad - 12, `${t2.kmh.toFixed(1)} km/h`, "#fcd34d", "#1a1405");
    }
  }
  function pill(x, y, text, bg, fg) {
    ctx.font = "700 11px Archivo, sans-serif";
    const w = ctx.measureText(text).width + 12;
    ctx.fillStyle = bg; roundRect(x - w / 2, y - 9, w, 18, 9); ctx.fill();
    ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y + 0.5);
  }

  function drawBall(b) {
    const s = view.s;
    const x = X(b[0]), y = Y(b[1]), lift = b[2] * s * 0.55, r = Math.max(4, 0.55 * s) * (1 + b[2] * 0.05);
    ctx.beginPath(); ctx.ellipse(x + 1 + lift * 0.15, y + 2, r * 0.9, r * 0.5, 0, 0, Math.PI * 2); ctx.fillStyle = `rgba(0,0,0,${0.4 - Math.min(0.25, b[2] * 0.03)})`; ctx.fill();
    ctx.beginPath(); ctx.arc(x, y - lift, r, 0, Math.PI * 2); ctx.fillStyle = "#fff"; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = "#111"; ctx.stroke();
    const since = performance.now() - S.flash;
    if (since < 1600) {
      ctx.beginPath(); ctx.arc(x, y - lift, r + since / 8, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,255,255,${1 - since / 1600})`; ctx.lineWidth = 3; ctx.stroke();
    }
  }

  function drawArrows() {
    for (const a of S.arrows) {
      const x0 = X(a.x0), y0 = Y(a.y0), x1 = X(a.x1), y1 = Y(a.y1);
      ctx.save();
      ctx.strokeStyle = a.color; ctx.fillStyle = a.color; ctx.lineWidth = a.w || 3;
      if (a.dash) ctx.setLineDash([8, 7]);
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.setLineDash([]);
      const ang = Math.atan2(y1 - y0, x1 - x0), h = 12;
      ctx.beginPath(); ctx.moveTo(x1, y1);
      ctx.lineTo(x1 - h * Math.cos(ang - 0.4), y1 - h * Math.sin(ang - 0.4));
      ctx.lineTo(x1 - h * Math.cos(ang + 0.4), y1 - h * Math.sin(ang + 0.4)); ctx.fill();
      if (a.label) {
        ctx.font = "700 12px Archivo, sans-serif";
        const w = ctx.measureText(a.label).width + 14;
        const lx = Math.min(x1 + 8, view.ox + L * view.s - w), ly = y1 - 24 + (a.dy || 0);
        ctx.fillStyle = "rgba(9,13,18,.92)"; roundRect(lx, ly, w, 22, 6); ctx.fill();
        ctx.fillStyle = a.color; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(a.label, lx + 7, ly + 11);
      }
      ctx.restore();
    }
  }
  function roundRect(x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  // ------------------------------------------------------------------ cues & overlays
  function lensText(cue) {
    const t = cue.text[S.lang] || cue.text.en;
    const lens = S.lens === "analyst" ? "analyst" : "casual";
    let full = S.lens.startsWith("club:") ? (t[S.lens] || t.casual) : t[lens];
    const more = t[`${lens}_more`];
    if (more && full.endsWith(more)) return { main: full.slice(0, full.length - more.length).trim(), more };
    return { main: full, more: "" };
  }
  function visibleForLens(cue) {
    const f = focusId();
    if (!f) return true;
    return cue.players.includes(f) || ["goal", "halftime", "fulltime", "red", "forecast"].includes(cue.kind);
  }

  function onCue(cue) {
    S.cues.push(cue);
    markGroup(cue.cue_id);
    if (["fulltime", "halftime", "goal", "chance", "turnover", "red"].includes(cue.kind)) drawRiver();
    if (cue.catchup || !visibleForLens(cue)) return;
    const txt = lensText(cue);
    if (cue.overlay === "impact") showImpact(cue, txt);
    else if (cue.overlay === "banner") showBanner(cue, txt);
    else if (cue.overlay === "meter") showMeter(cue, txt);
    else if (cue.overlay === "forecast") showForecastCard(cue, txt);
    else showTag(cue, txt);
    speak(`${txt.main} ${txt.more}`);
  }

  function clearCards() { $("overlays").querySelectorAll(".card").forEach((c) => c.remove()); }
  function teamOf(cue) { return cue.team === S.meta.home.id ? S.meta.home : S.meta.away; }

  function showImpact(cue, txt) {
    clearCards();
    const v = cue.values, team = teamOf(cue);
    const el = document.createElement("div");
    el.className = `card ${cue.kind}`;
    el.style.borderLeftColor = cue.kind === "goal" ? "#fff" : team.color;
    let bars = "", proof = "";
    if (cue.kind === "goal" || cue.kind === "turnover") {
      bars = swing(v.before, v.after, team.color, "win chance before → after");
      proof = cue.kind === "goal"
        ? `Proven: exact solve + ${v.n} forks agree (${v.fork}%) · ${cue.event_id} · ${cue.latency_ms} ms`
        : `Exact solve over the rest of the match · ${cue.event_id} · ${cue.latency_ms} ms`;
    } else if (cue.kind === "chance") {
      bars = swing(v.before, v.ifgoal, team.color, "win chance now → if it had gone in");
      proof = `Counterfactual: the same moment re-run as a goal · xG ${v.xg} · ${cue.event_id}`;
    }
    el.innerHTML = `<div class="k">${KIND_LABEL[cue.kind]} <span class="pill">${cue.clock}</span><span class="pill">${team.short}</span></div>
      <div class="line">${esc(txt.main)}</div>${bars}${txt.more ? `<div class="more">${esc(txt.more)}</div>` : ""}<div class="proof">${proof}</div>`;
    $("overlays").appendChild(el);
    requestAnimationFrame(() => requestAnimationFrame(() => el.querySelectorAll(".to").forEach((t) => t.style.width = t.dataset.w)));
    retire(el, cue.duration);
  }
  function swing(a, b, color, note) {
    return `<div class="swing"><span>${a}%</span><div class="track"><div class="from" style="width:${a}%"></div>
      <div class="to" data-w="${b}%" style="background:${color}"></div></div><span style="color:${color}">${b}%</span></div>
      <div class="proof" style="margin-top:3px">${note}</div>`;
  }
  function showForecastCard(cue, txt) {
    clearCards();
    const v = cue.values, h = S.meta.home, a = S.meta.away;
    const el = document.createElement("div");
    el.className = "card forecast";
    el.innerHTML = `<div class="k">${KIND_LABEL.forecast} <span class="pill">${cue.clock}</span><span class="pill">${v.mins}' left</span></div>
      <div class="fc-bar mini"><i style="width:${v.hw}%;background:${h.color}"></i><i style="width:${v.dw}%;background:var(--draw)"></i><i style="width:${v.aw}%;background:${a.color}"></i></div>
      <div class="fc-mini"><span style="color:${h.color}">${h.short} ${v.hw}%</span><span>draw ${v.dw}%</span><span style="color:${a.color}">${a.short} ${v.aw}%</span></div>
      <div class="line small">${esc(txt.main)}</div>
      <div class="proof">Exact joint-score solve · ${cue.event_id}</div>`;
    $("overlays").appendChild(el);
    retire(el, cue.duration);
  }
  function showBanner(cue, txt) {
    $("overlays").querySelectorAll(".banner").forEach((c) => c.remove());
    const el = document.createElement("div");
    el.className = `banner ${cue.kind === "red" ? "red" : ""}`;
    el.innerHTML = `<small>${KIND_LABEL[cue.kind]} · ${cue.clock}</small>${esc(txt.main)}${txt.more ? `<div class="more">${esc(txt.more)}</div>` : ""}`;
    $("overlays").appendChild(el);
    retire(el, cue.duration);
  }
  function showMeter(cue, txt) {
    const m = $("meter"), idx = cue.values.idx;
    m.hidden = false;
    m.innerHTML = `<div class="k" style="font-size:11px;font-weight:800;letter-spacing:.12em;color:${cue.kind === "control_chaos" ? "var(--bad)" : "var(--accent)"}">${KIND_LABEL[cue.kind]} · ${cue.clock}</div>
      <div class="mbar"><i style="left:${idx}%"></i></div><div style="font-size:12.5px;line-height:1.35">${esc(txt.main)}</div>`;
    clearTimeout(m._t); m._t = setTimeout(() => m.hidden = true, cue.duration * 1000 / Math.max(1, S.speed / 15));
  }
  function showTag(cue, txt) {
    const el = document.createElement("div");
    el.className = "tag";
    const v = cue.values;
    const big = cue.kind === "record_pass" ? `${v.succ}% pass` : cue.kind === "record_distance" ? `${v.km} km` : `${v.speed} km/h`;
    el.innerHTML = `${big} <small>${KIND_LABEL[cue.kind].toLowerCase()} · ${esc(v.player)}</small>`;
    el.title = txt.main;
    el.dataset.player = cue.players[0];
    $("overlays").appendChild(el);
    retire(el, cue.duration);
  }
  function positionTags(smp) {
    $("overlays").querySelectorAll(".tag").forEach((el) => {
      const s = S.slots.indexOf(el.dataset.player);
      if (s >= 0) { el.style.left = `${X(smp.pos[2 * s])}px`; el.style.top = `${Y(smp.pos[2 * s + 1]) - 14}px`; }
    });
  }
  function retire(el, seconds) {
    // cards stay readable at any playback speed: never shorter than 5 s of real time
    const ms = Math.max(5000, seconds * 1000 * Math.min(1, 15 / Math.max(1, S.speed)) * 1.0);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, ms);
  }
  function speak(text) {
    if (!S.voice || !("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text.replace(/\[e\d+\]/g, ""));
    u.lang = VOICE_LANG[S.lang] || "en-GB"; u.rate = 1.05;
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  }
  function vibrate(p) { if (navigator.vibrate) try { navigator.vibrate(p); } catch (e) { /* ignore */ } }

  // ------------------------------------------------------------------ newsroom
  const groups = new Map();
  function onTrace(t) {
    let g = groups.get(t.cue_id);
    if (!g) {
      g = document.createElement("li"); g.className = "group";
      g.innerHTML = `<div class="gh"><b>…</b><span>${t.clock}</span></div>`;
      g.onclick = () => inspect(t.cue_id);
      $("trace").prepend(g); groups.set(t.cue_id, g);
      while ($("trace").children.length > 60) { const last = $("trace").lastChild; groups.forEach((v, k) => { if (v === last) groups.delete(k); }); last.remove(); }
    }
    if (t.agent === "Spotter") {
      g.querySelector(".gh b").textContent = (t.msg.match(/Flagged ([a-z ]+)/) || [])[1] || "";
      g.dataset.event = (t.msg.match(/\[(e\d+)\]/) || [])[1] || "";
    }
    const step = document.createElement("div");
    step.className = `step ${t.status}`;
    step.innerHTML = `<span class="chip" style="background:${AGENT_COLORS[t.agent]}">${t.agent}</span>
      <span class="msg">${esc(t.msg)} ${t.ms != null ? `<span class="ms">${t.ms} ms</span>` : ""}</span>`;
    g.appendChild(step);
    if (t.status === "drop") g.classList.add("dropped");
  }
  function markGroup(id) { const g = groups.get(id); if (g) { g.classList.add("aired"); g.classList.remove("dropped"); } }

  async function inspect(cueId) {
    const g = groups.get(cueId); if (!g || !g.dataset.event) return;
    showTab("lab");
    $("forkOut").innerHTML = `<div class="res">Running 1,000 forks before and after ${g.dataset.event}…</div>`;
    const q = new URLSearchParams({ home: S.meta.home.id, away: S.meta.away.id, seed: S.meta.seed, event_id: g.dataset.event, n: 1000 });
    const r = await fetch(`/api/impact?${q}`).then((x) => x.json());
    const f = r.forks;
    $("forkOut").innerHTML = `<div class="res"><h5>Fork Inspector · ${g.dataset.event} · ${r.ms} ms</h5>
      <div class="row"><span>${S.meta.home.short} win (exact)</span><span>${pc(r.before.home_win)} → <b>${pc(r.after.home_win)}</b></span></div>
      <div class="row"><span>${S.meta.home.short} win (1,000 forks)</span><span>${pc(f.before.home_win)} → <b>${pc(f.after.home_win)}</b> ±${pc(f.after.home_win_ci95)}</span></div>
      <div class="row"><span>Chance this possession scores</span><span>${pc(r.before.threat, 1)} → ${pc(r.after.threat, 1)}</span></div>
      <div class="row"><span>Most likely final score after</span><span>${r.after.scorelines.slice(0, 2).map((s) => `${s.score[0]}–${s.score[1]} (${pc(s.p)})`).join(" · ")}</span></div>
      <h5 style="margin-top:10px">Final goal difference across 1,000 futures (${S.meta.home.short} − ${S.meta.away.short})</h5>
      ${hist(f.before.final_diff_hist, f.after.final_diff_hist)}
      <div class="row" style="margin-top:6px"><span><i class="sw" style="background:#5b6676"></i> before</span><span><i class="sw" style="background:var(--accent)"></i> after</span></div></div>`;
  }
  function hist(a, b) {
    const keys = [...new Set([...Object.keys(a), ...Object.keys(b)].map(Number))].sort((x, y) => x - y).filter((k) => k >= -5 && k <= 5);
    const max = Math.max(...keys.map((k) => Math.max(a[k] || 0, b[k] || 0)), 1);
    return `<div class="hist">${keys.map((k) => `<div><div style="display:flex;gap:1px;align-items:flex-end;height:100%;width:100%">
      <i style="height:${(a[k] || 0) / max * 100}%;background:#5b6676"></i><i style="height:${(b[k] || 0) / max * 100}%;background:var(--accent)"></i></div>
      <span>${k > 0 ? "+" + k : k}</span></div>`).join("")}</div>`;
  }

  // ------------------------------------------------------------------ outlook, forecast & river
  function onOutlook(o) {
    S.outlook = o;
    S.river.push({ T: o.T, h: o.home_win, d: o.draw, a: o.away_win });
    renderOutlook(); renderForecast(); drawRiver();
  }
  function renderOutlook() {
    const o = S.outlook; if (!o || !S.meta) return;
    const h = o.home_win * 100, d = o.draw * 100, a = o.away_win * 100;
    $("olH").style.width = `${h}%`; $("olD").style.width = `${d}%`; $("olA").style.width = `${a}%`;
    $("olTxt").innerHTML = `<span>${S.meta.home.short} ${h.toFixed(0)}%</span><span>draw ${d.toFixed(0)}%</span><span>${S.meta.away.short} ${a.toFixed(0)}%</span>`;
  }
  function storyText(o) {
    if (!o || !o.story) return "";
    const t = o.story[S.lang] || o.story.en;
    return S.lens === "analyst" ? t.analyst : t.casual;
  }
  function renderForecast() {
    const o = S.outlook; if (!o || !S.meta) return;
    const h = S.meta.home, a = S.meta.away;
    $("fcClock").textContent = o.clock === "Pre-match" ? "Pre-match" : `${o.clock} · ${o.score[0]}–${o.score[1]}`;
    $("fcLeft").textContent = o.mins_left != null ? `${o.mins_left} min to play` : "";
    $("fcH").style.width = `${o.home_win * 100}%`; $("fcD").style.width = `${o.draw * 100}%`; $("fcA").style.width = `${o.away_win * 100}%`;
    $("fcLabels").innerHTML = `<span style="color:${h.color}">${esc(h.name)} <b>${pc(o.home_win)}</b></span><span>Draw <b>${pc(o.draw)}</b></span><span style="color:${a.color}"><b>${pc(o.away_win)}</b> ${esc(a.name)}</span>`;
    const story = storyText(o);
    $("fcStory").textContent = story;
    $("storyLine").innerHTML = story ? `<b>Forecast</b> ${esc(story)}` : "";
    const top = o.scorelines[0].p;
    $("fcScores").innerHTML = o.scorelines.map((s, i) => `<div class="sc ${i === 0 ? "top" : ""}"><b>${s.score[0]}–${s.score[1]}</b><div class="scbar"><i style="width:${s.p / top * 100}%"></i></div><span>${pc(s.p)}</span></div>`).join("");
    const ng = o.next_goal, n10 = o.next_goal_10;
    $("fcNext").innerHTML = [[h.name, ng.home, h.color], [a.name, ng.away, a.color], ["Nobody", ng.none, "var(--draw)"]].map(([n, p, c]) =>
      `<div class="ng"><span>${esc(n)}</span><div class="scbar"><i style="width:${p * 100}%;background:${c}"></i></div><b>${pc(p)}</b></div>`).join("") +
      `<div class="fc-note" style="margin-top:6px">Chance of a goal in the next 10 minutes: <b>${pc(1 - n10.none)}</b></div>`;
    $("fcXg").innerHTML = `<div class="ng"><span>${esc(h.name)}</span><b>${o.exp_goals_left[0].toFixed(2)}</b></div><div class="ng"><span>${esc(a.name)}</span><b>${o.exp_goals_left[1].toFixed(2)}</b></div>`;
  }

  function tl() { return S.meta ? S.meta.timeline : { p1_end: 2800, p2_start: 2812, end: 5900 }; }
  function TofMinute(m) { const t = tl(); return m <= 45 ? m * 60 : t.p2_start + (m - 45) * 60; }
  function minuteLabel(T) {
    const t = tl();
    if (T <= t.p1_end) { const m = T / 60; return m > 45 ? `45+${Math.ceil(m - 45)}` : `${Math.floor(m)}'`; }
    const m = 45 + (T - t.p2_start) / 60; return m > 90 ? `90+${Math.ceil(m - 90)}` : `${Math.floor(m)}'`;
  }
  function drawRiver() {
    const r = river.getBoundingClientRect(); const w = r.width, h = r.height;
    rctx.clearRect(0, 0, w, h);
    if (!S.meta) return;
    const padL = 34, padR = 10, padT = 6, padB = 18;
    const maxT = Math.max(tl().end + 30, TofMinute(96));
    const xm = (T) => padL + (T / maxT) * (w - padL - padR);
    const yv = (v) => padT + (1 - v) * (h - padT - padB);
    rctx.fillStyle = "rgba(255,255,255,.03)"; rctx.fillRect(padL, padT, w - padL - padR, h - padT - padB);
    rctx.font = "10.5px JetBrains Mono, monospace"; rctx.fillStyle = "#8794a3"; rctx.textAlign = "right"; rctx.textBaseline = "middle";
    for (const v of [0, 0.5, 1]) { rctx.fillText(`${v * 100}%`, padL - 6, yv(v)); rctx.strokeStyle = "rgba(255,255,255,.06)"; rctx.beginPath(); rctx.moveTo(padL, yv(v)); rctx.lineTo(w - padR, yv(v)); rctx.stroke(); }
    rctx.textAlign = "center";
    for (const m of [0, 15, 30, 45, 60, 75, 90]) rctx.fillText(`${m}'`, xm(TofMinute(m)), h - 7);
    const pts = S.river;
    if (pts.length > 1) {
      const band = (top, bottom, color) => {
        rctx.beginPath();
        pts.forEach((p, i) => { const x = xm(p.T), y = yv(top(p)); i ? rctx.lineTo(x, y) : rctx.moveTo(x, y); });
        for (let i = pts.length - 1; i >= 0; i--) rctx.lineTo(xm(pts[i].T), yv(bottom(pts[i])));
        rctx.closePath(); rctx.fillStyle = color; rctx.fill();
      };
      band(() => 1, (p) => 1 - p.h, hexA(S.meta.home.color, 0.85));
      band((p) => 1 - p.h, (p) => p.a, "rgba(91,102,118,.55)");
      band((p) => p.a, () => 0, hexA(S.meta.away.color, 0.85));
      const last = pts[pts.length - 1];
      rctx.strokeStyle = "#fff"; rctx.setLineDash([3, 3]); rctx.beginPath(); rctx.moveTo(xm(last.T), padT); rctx.lineTo(xm(last.T), h - padB); rctx.stroke(); rctx.setLineDash([]);
      const x0 = xm(last.T) + 1, x1 = xm(maxT);
      if (x1 > x0 + 4 && !S.endReceived) {
        rctx.globalAlpha = 0.2;
        rctx.fillStyle = S.meta.home.color; rctx.fillRect(x0, yv(1), x1 - x0, yv(1 - last.h) - yv(1));
        rctx.fillStyle = "#5b6676"; rctx.fillRect(x0, yv(1 - last.h), x1 - x0, yv(last.a) - yv(1 - last.h));
        rctx.fillStyle = S.meta.away.color; rctx.fillRect(x0, yv(last.a), x1 - x0, yv(0) - yv(last.a));
        rctx.globalAlpha = 1;
      }
    }
    S.cueMarks = [];
    for (const c of S.cues) {
      if (!["goal", "turnover", "chance", "red"].includes(c.kind)) continue;
      const x = xm(c.T), d = c.evidence && c.evidence.delta ? c.evidence.delta : 0;
      const y = c.kind === "goal" ? padT + 8 : h - padB - 8;
      rctx.beginPath(); rctx.arc(x, y, c.kind === "goal" ? 6 : 3.5, 0, Math.PI * 2);
      rctx.fillStyle = c.kind === "goal" ? "#fff" : c.kind === "chance" ? "#fbbf24" : c.kind === "red" ? "#f87171" : "#c6f432"; rctx.fill();
      rctx.strokeStyle = "#0a0e13"; rctx.lineWidth = 1.5; rctx.stroke();
      if (c.kind === "goal") { rctx.fillStyle = "#fff"; rctx.font = "700 10.5px JetBrains Mono, monospace"; rctx.fillText(`${d >= 0 ? "+" : ""}${(d * 100).toFixed(0)}`, x, y + 15); }
      S.cueMarks.push({ x, y, c });
    }
  }
  function onRiverHover(e) {
    const r = river.getBoundingClientRect(); const mx = e.clientX - r.left, my = e.clientY - r.top;
    const hit = (S.cueMarks || []).find((m) => Math.hypot(m.x - mx, m.y - my) < 10);
    const tip = $("riverTip");
    if (!hit) { tip.hidden = true; return; }
    const c = hit.c, t = lensText(c);
    tip.hidden = false;
    tip.innerHTML = `<b>${c.clock} · ${KIND_LABEL[c.kind]}</b><br>${esc(t.main)}${t.more ? `<br><span class="muted">${esc(t.more)}</span>` : ""}`;
    tip.style.left = `${Math.min(mx + 12, r.width - 330)}px`; tip.style.top = `${Math.max(0, my - 90)}px`;
  }

  // ------------------------------------------------------------------ stats
  function onStats(s) {
    S.lastStats = s;
    const h = S.meta.home, a = S.meta.away, th = s.teams[h.id], ta = s.teams[a.id];
    const km = s.physical ? s.physical.team_km : null;
    const rows = [
      ["Possession", th.possession * 100, ta.possession * 100, (v) => `${v.toFixed(0)}%`],
      ["xG", th.xg, ta.xg, (v) => v.toFixed(2)],
      ["Shots", th.shots, ta.shots, (v) => v],
      ["On target", th.on_target, ta.on_target, (v) => v],
      ["Passes", th.passes, ta.passes, (v) => v],
      ["Pass completion", th.pass_completion * 100, ta.pass_completion * 100, (v) => `${v.toFixed(0)}%`],
      ["Final-third entries", th.final_third_entries, ta.final_third_entries, (v) => v],
      ["Turnovers won", th.turnovers_won, ta.turnovers_won, (v) => v],
      ...(km ? [["Distance covered (km)", km[h.id], km[a.id], (v) => v.toFixed(1)]] : []),
      ["Fouls", th.fouls, ta.fouls, (v) => v],
    ];
    $("statsTeams").innerHTML = `<div class="stat-row" style="font-family:var(--sans);font-weight:800"><span style="color:${h.color}">${h.short}</span><span></span><span class="r" style="color:${a.color}">${a.short}</span></div>` +
      rows.map(([l, x, y, f]) => {
        const t = (x + y) || 1;
        return `<div class="stat-row"><span class="lbl">${l}</span><span>${f(x)}</span><div class="bars"><i style="width:${x / t * 100}%;background:${h.color}"></i><i style="width:${y / t * 100}%;background:${a.color}"></i></div><span class="r">${f(y)}</span></div>`;
      }).join("");
    const ci = s.control;
    $("gaugeFill").style.setProperty("--v", `${ci.index}%`);
    $("gaugeVal").textContent = `${ci.index}/100`;
    if (s.physical) {
      const p = s.physical, col = (t) => (t === h.id ? h.color : a.color);
      $("physical").innerHTML =
        p.distance.slice(0, 3).map((r) => `<div><span><i class="sw" style="background:${col(r.team)}"></i>${esc(r.name)}</span><b>${r.km.toFixed(1)} km</b></div>`).join("") +
        p.speed.slice(0, 3).map((r) => `<div><span><i class="sw" style="background:${col(r.team)}"></i>${esc(r.name)} · top speed</span><b>${r.top_kmh.toFixed(1)} km/h</b></div>`).join("");
    }
    const rec = s.records, nm = (pid) => (S.players.get(pid) || {}).name || "?";
    $("records").innerHTML = [
      rec.fastest_shot && `<div><span>Fastest shot · ${esc(nm(rec.fastest_shot.player))}</span><b>${rec.fastest_shot.value.toFixed(1)} km/h</b></div>`,
      rec.hardest_pass && `<div><span>Hardest pass · ${esc(nm(rec.hardest_pass.player))}</span><b>${rec.hardest_pass.value}/100</b></div>`,
    ].filter(Boolean).join("") || `<div><span class="muted">No records yet</span></div>`;
    updateTape(s.ops);
    renderPlayerCard();
  }
  function renderPlayerCard() {
    const f = focusId();
    if (!f || !S.lastStats) { $("playerCard").innerHTML = ""; return; }
    const p = S.players.get(f);
    const all = S.lastStats.physical ? [...S.lastStats.physical.distance, ...S.lastStats.physical.speed] : [];
    const me = all.find((r) => r.player === f);
    $("playerCard").innerHTML = `<h4>Player focus · ${esc(p.name)} <span class="muted">#${p.number} ${p.role}</span></h4>
      <div class="res"><div class="row"><span>Cues are filtered to moments involving ${esc(p.short)}; his name tag follows him on the pitch.</span></div>
      ${me ? `<div class="row"><span>Distance</span><b>${me.km.toFixed(1)} km</b></div><div class="row"><span>Top speed</span><b>${me.top_kmh.toFixed(1)} km/h</b></div>` : ""}</div>`;
  }
  function updateTape(o) {
    if (!o) return;
    $("tape").innerHTML = `<span>cues aired <b>${o.cues_aired}</b></span><span>held by Director <b>${o.held}</b></span>
      <span>rejected by Skeptic <b>${o.rejected}</b></span><span>pipeline p50 <b>${o.latency_p50_ms} ms</b></span>
      <span>p99 <b>${o.latency_p99_ms} ms</b></span><span>forks run <b>${(o.forks_run || 0).toLocaleString()}</b></span>
      <span>tracking <b>5 Hz · 22 players</b></span><span>narration <b>${o.model}</b></span>${S.meta ? `<span>bus <b>${S.meta.bus}</b></span>` : ""}`;
  }

  // ------------------------------------------------------------------ Moment Lab
  function labFreeze() {
    if (!S.lastOnBall || !S.meta) return;
    showTab("lab");
    setPaused(true);
    const ev = S.lastOnBall;
    S.lab = { ev };
    S.playT = ev.T;  // rewind the picture to the exact moment
    $("overlays").innerHTML = ""; $("meter").hidden = true;
    S.arrows = ev.end_x != null ? [{ x0: ev.x, y0: ev.y, x1: ev.end_x, y1: ev.end_y, color: "rgba(255,255,255,.9)", dash: true, label: "what happened" }] : [];
    const p = S.players.get(ev.player) || {};
    $("broadcast").classList.add("lab");
    $("labHint").hidden = false;
    $("labHint").textContent = `${ev.clock} · ${p.name || "Player"} on the ball. Click to play your pass.`;
    $("labOut").innerHTML = `<div class="res"><h5>Frozen at ${ev.clock}</h5>${esc(p.name || "")} has the ball (${ev.type}). Click anywhere on the pitch to choose a pass.</div>`;
  }
  async function onPitchClick(e) {
    if (!S.lab) return;
    const r = pitch.getBoundingClientRect();
    const x = (e.clientX - r.left - view.ox) / view.s, y = (e.clientY - r.top - view.oy) / view.s;
    if (x < 0 || x > L || y < 0 || y > W) return;
    const ev = S.lab.ev;
    $("labHint").textContent = "Replaying 2,000 futures…";
    const res = await fetch("/api/play", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ home: S.meta.home.id, away: S.meta.away.id, seed: S.meta.seed, event_id: ev.event_id, x, y }) }).then((x) => x.json());
    if (res.detail) { $("labOut").innerHTML = `<div class="res">${esc(res.detail)}</div>`; return; }
    const team = res.team_index === 0 ? S.meta.home : S.meta.away;
    S.arrows = [
      ...(ev.end_x != null ? [{ x0: ev.x, y0: ev.y, x1: ev.end_x, y1: ev.end_y, color: "rgba(255,255,255,.9)", dash: true, label: "what happened" }] : []),
      { x0: ev.x, y0: ev.y, x1: res.best.to.x, y1: res.best.to.y, color: "#c6f432", label: `best · lands ${pc(res.best.success_prob)}`, dy: -14 },
      { x0: ev.x, y0: ev.y, x1: res.yours.to.x, y1: res.yours.to.y, color: "#fbbf24", w: 4, label: `yours · lands ${pc(res.yours.success_prob)}`, dy: 14 },
    ];
    $("labHint").textContent = "Your pass, replayed. Click again to try another, or Resume.";
    const wk = res.team_index === 0 ? "home_win" : "away_win";
    const mixed = res.yours.forks.mixed[wk];
    const dpts = res.verdict_delta_ep * 100;
    const verdict = dpts > 0.05 ? `Better than what happened: worth ${dpts.toFixed(1)} points per 100 moments like this.`
      : dpts < -0.05 ? `Worse than what happened: costs ${Math.abs(dpts).toFixed(1)} points per 100 moments like this.`
      : "About as good as what happened.";
    const why = res.yours.success_prob < 0.6
      ? `It is a risky ball: it only arrives ${pc(res.yours.success_prob)} of the time, and losing it here hands ${res.team_index === 0 ? S.meta.away.short : S.meta.home.short} the ball.`
      : res.yours.threat > 0.03 ? `It puts the attack where goals come from: this possession would score ${pc(res.yours.threat, 1)} of the time.`
      : `It keeps the ball (${pc(res.yours.success_prob)} arrive) but doesn't create much danger (${pc(res.yours.threat, 1)} chance this attack scores).`;
    $("labOut").innerHTML = `
      <div class="res"><h5>What happened · ${esc(res.actual.type)} · ${esc(res.actual.outcome || "")}</h5>
        <div class="row"><span>${team.short} win chance after</span><b>${pc(res.actual.win_prob, 1)}</b></div></div>
      <div class="res you"><h5>Your pass · ${res.yours.length} m · difficulty ${res.yours.difficulty}/100</h5>
        <div class="big">${pc(res.yours.success_prob)} <span class="muted" style="font-size:13px">lands</span></div>
        <div class="row"><span>${team.short} win chance (exact)</span><b>${pc(res.yours.win_prob, 1)}</b></div>
        <div class="row"><span>${team.short} win chance (2,000 forks)</span><b>${pc(mixed, 1)}</b></div>
        <div class="row"><span>Chance this attack scores</span><b>${pc(res.yours.threat, 1)}</b></div></div>
      <div class="res win"><h5>Best option the engine found</h5>
        <div class="row"><span>${res.best.length} m · lands ${pc(res.best.success_prob)}</span><b>${pc(res.best.win_prob, 1)}</b></div></div>
      <div class="res"><div class="verdict">${verdict}</div><div style="font-size:13px;margin-top:6px;line-height:1.45">${why}</div>
        <div class="muted" style="font-size:12px;margin-top:6px">Computed in ${res.ms} ms on the same world model that generated the match.</div></div>`;
  }
  async function labDuel() {
    if (!S.lab) labFreeze();
    if (!S.lab) return;
    const ev = S.lab.ev;
    const q = new URLSearchParams({ home: S.meta.home.id, away: S.meta.away.id, seed: S.meta.seed, event_id: ev.event_id });
    $("labOut").innerHTML = `<div class="res">The pundits are arguing…</div>`;
    $("labHint").hidden = false; $("labHint").textContent = "Pundit Duel: two philosophies, one simulator referee.";
    const d = await fetch(`/api/duel?${q}`).then((x) => x.json());
    if (d.detail) { $("labOut").innerHTML = `<div class="res">${esc(d.detail)}</div>`; return; }
    const [pu, di] = d.pundits;
    S.arrows = [
      { x0: ev.x, y0: ev.y, x1: pu.option.to.x, y1: pu.option.to.y, color: "#7dd3fc", label: `Purist · ${pc(pu.option.success_prob)}`, dy: -14 },
      { x0: ev.x, y0: ev.y, x1: di.option.to.x, y1: di.option.to.y, color: "#fdba74", label: `Direct · ${pc(di.option.success_prob)}`, dy: 14 },
    ];
    const win = (n) => d.winner === n ? "win" : "";
    $("labOut").innerHTML = `
      <div class="res ${win(pu.name)}"><h5 style="color:#7dd3fc">${pu.name}</h5>${esc(pu.line)}</div>
      <div class="res ${win(di.name)}"><h5 style="color:#fdba74">${di.name}</h5>${esc(di.line)}</div>
      <div class="res"><h5 style="color:var(--accent)">Simulator referee</h5><div class="verdict">${esc(d.verdict)}</div></div>`;
    speak(`${pu.line} ${di.line} ${d.verdict}`);
  }
  function labResume() {
    S.lab = null; S.arrows = [];
    $("broadcast").classList.remove("lab"); $("labHint").hidden = true;
    setPaused(false);
  }

  // ------------------------------------------------------------------ recap
  function onRecap(r) {
    S.recap = r;
    showRecap(r);
    if (S.lang !== "en") fetch(`/api/recap?${new URLSearchParams({ home: S.meta.home.id, away: S.meta.away.id, seed: S.meta.seed, lang: S.lang })}`)
      .then((x) => x.json()).then((rr) => { S.recap = rr; showRecap(rr); });
  }
  function showRecap(r) {
    $("recapBody").innerHTML = `<div class="recap-headline">${esc(r.headline)}</div><div class="muted">${esc(r.analyst)}</div>
      <h4>Moments that changed the match <span class="muted">(measured swing in win probability)</span></h4>
      ${r.moments.map((m) => `<div class="recap-m"><span class="c">${m.clock}</span><span>${esc(m.line)}</span><span class="d">${m.delta >= 0 ? "+" : ""}${(m.delta * 100).toFixed(1)}</span></div>`).join("")}
      ${(r.missed_chances || []).length ? `<h4>Chances that would have changed it <span class="muted">(value of a goal, had it gone in)</span></h4>` +
        r.missed_chances.map((m) => `<div class="recap-m"><span class="c">${m.clock}</span><span>${esc(m.line)}</span><span class="d" style="color:var(--warn)">+${(m.goal_value * 100).toFixed(1)}</span></div>`).join("") : ""}`;
    $("recap").hidden = false;
  }

  // ------------------------------------------------------------------ utils
  function pc(v, dp = 0) { return `${(v * 100).toFixed(dp)}%`; }
  function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; }
  function download(name, data) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  init();
})();
