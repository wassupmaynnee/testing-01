/* ===========================================================================
   Clippify dashboard controller.
   FROZEN UI CONTRACT:
     - AppState holds all client state under stable data keys.
     - ONE delegated [data-action] click switch (no per-element handlers).
     - Every network call expects the {ok, data | error} envelope.
     - SSE events map to STEP_LABELS, pipeline stages 0 -> 6.
   ========================================================================= */

// Must mirror saas/sse.py STEP_LABELS exactly (stages 0..6).
const STEP_LABELS = [
  "Queued",
  "Probing media",
  "Transcribing (ASR)",
  "Scoring engagement",
  "Selecting clip boundaries",
  "Rendering (cut · reframe · subtitles)",
  "Complete",
];

// --- AppState: single source of client truth ---
const AppState = {
  user: null,        // {id,email,credits}
  file: null,        // selected File
  jobs: [],          // [{id,status,stage,...}]
  activeJobId: null, // job currently streaming
  stage: 0,          // current STEP_LABELS index 0..6
  progress: 0,       // 0..1
  clip: null,        // {id,title,score,signals,fileUrl,downloadUrl}
  sse: null,         // EventSource handle
  publish: { enabled: false, accounts: [] }, // OAuth publish destinations
  clipsOffset: 0,    // pagination cursor for the clip library
  clipsTotal: 0,     // total clips owned by the user
  optimisticJob: null, // {startedAt, failed, stalled, error} — processing card
  lastSubmit: null,    // {type:'url'|'file', url?} for one-click Retry
  heartbeat: null,     // SSE staleness watchdog
  lastEventAt: 0,
  referrals: null,
};

const CLIPS_PAGE = 12;

// --- envelope-aware fetch ---
async function api(path, opts = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...opts });
  let env;
  try { env = await res.json(); }
  catch { throw { code: "bad_response", message: `HTTP ${res.status}` }; }
  if (!env.ok) throw env.error || { code: "error", message: "Request failed" };
  return env.data;
}

const $ = (id) => document.getElementById(id);

/* ===========================================================================
   Client cache — stale-while-revalidate with localStorage persistence.
   Cached revisits render instantly; a background refetch then reconciles.
   Whitelist only (never tokens/secrets — the session lives in the httpOnly
   mf_session cookie, which JS can't read anyway).
   ========================================================================= */
const CACHE_NS = "clippify.cache.v1";
const CACHE_TTLS = { me: 60_000, clips: 30_000, publish: 60_000, analytics: 60_000, referrals: 60_000 };
const CACHE_PERSIST = new Set(["me", "clips", "publish", "referrals"]); // analytics stays session-only
const Cache = {
  _mem: {},
  _load() {
    if (this._loaded) return;
    this._loaded = true;
    try {
      const raw = JSON.parse(localStorage.getItem(CACHE_NS)) || {};
      for (const k of Object.keys(raw)) if (CACHE_PERSIST.has(k)) this._mem[k] = raw[k];
    } catch (_) { /* corrupt cache -> cold start */ }
  },
  _save() {
    const out = {};
    for (const k of Object.keys(this._mem)) if (CACHE_PERSIST.has(k)) out[k] = this._mem[k];
    try { localStorage.setItem(CACHE_NS, JSON.stringify(out)); } catch (_) { /* quota */ }
  },
  get(key) {
    this._load();
    const e = this._mem[key];
    if (!e) return { data: null, fresh: false };
    return { data: e.data, fresh: Date.now() - e.t < (CACHE_TTLS[key] || 30_000) };
  },
  set(key, data) { this._load(); this._mem[key] = { data, t: Date.now() }; this._save(); },
  invalidate(...keys) {
    this._load();
    for (const k of keys) delete this._mem[k];
    this._save();
  },
};

/* --- animated count-up for the credits badge --- */
let _lastCredits = null;
function setCredits(n) {
  const el = $("credits");
  if (!el) return;
  const from = _lastCredits;
  _lastCredits = n;
  if (from === null || from === n || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = n;
    return;
  }
  const t0 = performance.now(), dur = 500;
  (function step(t) {
    const p = Math.min((t - t0) / dur, 1);
    el.textContent = Math.round(from + (n - from) * p);
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}

/* ===========================================================================
   Tooltip engine — one delegated primitive for every [data-tip] control.
   Hover + keyboard focus, 300ms delay, aria-describedby, never blocks clicks.
   ========================================================================= */
(function tooltips() {
  const tip = document.createElement("div");
  tip.id = "tt";
  tip.setAttribute("role", "tooltip");
  tip.style.cssText =
    "position:fixed; z-index:90; max-width:240px; padding:6px 10px; border-radius:8px;" +
    "font-size:12px; line-height:1.35; background:rgba(10,10,10,.95); color:#fff;" +
    "border:1px solid rgba(255,255,255,.14); pointer-events:none; opacity:0;" +
    "transition:opacity .15s; visibility:hidden";
  document.addEventListener("DOMContentLoaded", () => document.body.appendChild(tip));
  let timer = null, current = null;
  function show(el) {
    const text = el.getAttribute("data-tip");
    if (!text) return;
    tip.textContent = text;
    tip.style.visibility = "visible";
    const r = el.getBoundingClientRect();
    tip.style.left = Math.max(8, Math.min(r.left + r.width / 2 - 120, innerWidth - 248)) + "px";
    tip.style.top = (r.top > 60 ? r.top - tip.offsetHeight - 8 : r.bottom + 8) + "px";
    tip.style.opacity = "1";
    el.setAttribute("aria-describedby", "tt");
    current = el;
  }
  function hide() {
    clearTimeout(timer);
    tip.style.opacity = "0";
    tip.style.visibility = "hidden";
    if (current) { current.removeAttribute("aria-describedby"); current = null; }
  }
  for (const [enter, leave] of [["mouseover", "mouseout"], ["focusin", "focusout"]]) {
    document.addEventListener(enter, (e) => {
      const el = e.target.closest("[data-tip]");
      if (!el || el === current) return;
      clearTimeout(timer);
      timer = setTimeout(() => show(el), 300);
    });
    document.addEventListener(leave, (e) => {
      if (e.target.closest("[data-tip]")) hide();
    });
  }
  document.addEventListener("scroll", hide, true);
})();

function toast(message, kind = "ok") {
  const t = $("toast");
  t.textContent = message;
  t.className = `toast ${kind}`;
  setTimeout(() => t.classList.add("hidden"), 3200);
}

// --- rendering ---
function renderUser() {
  $("view-login").classList.toggle("hidden", !!AppState.user);
  $("view-app").classList.toggle("hidden", !AppState.user);
  const bar = $("userbar");
  if (AppState.user) {
    const tier = AppState.user.tier ? AppState.user.tier[0].toUpperCase() + AppState.user.tier.slice(1) : "Free";
    bar.innerHTML =
      `<span class="muted" style="margin-right:12px">${AppState.user.email}</span>` +
      `<span class="chip" style="margin-right:10px">${tier}</span>` +
      `<a class="btn" href="/#pricing" data-tip="More credits every month">Upgrade</a>` +
      `<button class="btn" data-action="billing-portal" data-tip="Manage or cancel your plan">Billing</button>` +
      `<button class="btn" data-action="logout" data-tip="Sign out of Clippify">Sign out</button>`;
    setCredits(AppState.user.credits);
  } else {
    bar.innerHTML = "";
  }
}

function renderStepper() {
  const el = $("stepper");
  el.innerHTML = STEP_LABELS.map((label, i) => {
    const cls = i < AppState.stage ? "done" : i === AppState.stage ? "active" : "";
    const mark = i < AppState.stage ? "✓" : i;
    return `<div class="step ${cls}"><div class="dot">${mark}</div><div>${label}</div></div>`;
  }).join("");
  const pct = Math.round(AppState.progress * 100);
  $("progbar").style.width = `${pct}%`;
  const wrap = $("progwrap");
  if (wrap) wrap.setAttribute("aria-valuenow", String(pct));
}

function renderJobs() {
  const el = $("joblist");
  if (!AppState.jobs.length) {
    el.innerHTML = `<p class="faint">No jobs yet — add a video above and your first clips land here.</p>`;
    return;
  }
  el.innerHTML = AppState.jobs.map((j) => `
    <div class="jobrow" data-action="open-job" data-job="${j.id}" role="button" tabindex="0">
      <div><div>Job ${j.id.slice(0, 8)}</div>
        <div class="faint" style="font-size:12px">stage ${j.stage}/6</div></div>
      <span class="status-tag status-${j.status}">${j.status}</span>
    </div>`).join("");
}

// One honest line about WHY a clip scored what it did, from its own signals
// (frozen weights: hook .35 / pace .20 / sentiment .25 / face .20).
function whyLine(score, s) {
  if (!s) return "";
  const parts = [
    { k: "hook", v: s.hook ?? 0, txt: "opens strong" },
    { k: "pace", v: s.pace ?? 0, txt: "keeps a fast pace" },
    { k: "sentiment", v: s.sentiment ?? 0, txt: "carries emotional punch" },
    { k: "face", v: s.face ?? 0, txt: "keeps a face on screen" },
  ].sort((a, b) => b.v - a.v);
  const top = parts[0];
  if (top.v <= 0.05) return "Scored low across all signals — quieter moment.";
  return `Scored highest on ${top.k} — this moment ${top.txt}.`;
}

function renderClip() {
  const has = !!AppState.clip;
  $("clip-empty").classList.toggle("hidden", has);
  $("clip-box").classList.toggle("hidden", !has);
  renderSample();
  if (!has) return;
  const c = AppState.clip;
  const vid = $("clip-video");
  vid.src = c.fileUrl;
  if (c.thumbUrl) vid.poster = c.thumbUrl;
  vid.preload = "metadata";
  $("clip-score").textContent = `★ ${(c.score ?? 0).toFixed(3)}`;
  $("download-link").href = c.downloadUrl;
  const why = $("clip-why");
  if (why) {
    const srcLabel = c.source ? (c.source.kind === "youtube" ? c.source.ref : "uploaded video") : "";
    const meta = [
      srcLabel && `From ${srcLabel}`,
      (c.startS != null && c.endS != null) && `${c.startS.toFixed(1)}s–${c.endS.toFixed(1)}s`,
      c.duration && `${Math.round(c.duration)}s`,
      c.aspect,
    ].filter(Boolean).join(" · ");
    why.textContent = `${whyLine(c.score, c.signals)}${meta ? "  (" + meta + ")" : ""}`;
  }
  // Export presets — same post-ready file, platform-named download.
  document.querySelectorAll("#preset-row [data-preset]").forEach((a) => {
    a.href = c.downloadUrl;
    a.setAttribute("download", `clippify-${a.dataset.preset}-${(c.id || "clip").slice(0, 8)}.mp4`);
  });
  const s = c.signals || {};
  $("clip-signals").innerHTML = `
    <div><b>${(s.hook ?? 0).toFixed(2)}</b>hook</div>
    <div><b>${(s.pace ?? 0).toFixed(2)}</b>pace</div>
    <div><b>${(s.sentiment ?? 0).toFixed(2)}</b>sentiment</div>
    <div><b>${(s.face ?? 0).toFixed(2)}</b>face</div>`;
  markOnboarding("review");
}

// --- Sample project: new accounts see real output, not an empty box ---
let SAMPLE = null; // first showcase manifest entry, if present
async function loadSample() {
  try {
    const r = await fetch("/static/showcase/manifest.json");
    if (r.ok) { const m = await r.json(); if (Array.isArray(m) && m.length) SAMPLE = m[0]; }
  } catch (_) { /* no sample available */ }
  renderSample();
}
function renderSample() {
  const box = $("sample-project");
  if (!box) return;
  const showSample = !AppState.clip && !AppState.jobs.length && SAMPLE;
  box.style.display = showSample ? "block" : "none";
  const msg = $("clip-empty-msg");
  if (msg) msg.textContent = showSample
    ? "Here's what output looks like — this is a finished sample clip:"
    : "Your finished vertical clip will appear here.";
  if (showSample) {
    const v = $("sample-video");
    if (v && !v.src) {
      v.src = `/static/showcase/${SAMPLE.file}`;
      v.poster = `/static/showcase/${SAMPLE.poster}`;
    }
  }
}

// --- Onboarding checklist (localStorage-persisted, dismissible) ---
const OB_KEY = "clippify.onboarding";
function obState() {
  try { return JSON.parse(localStorage.getItem(OB_KEY)) || {}; } catch (_) { return {}; }
}
function markOnboarding(step) {
  const st = obState();
  if (st.dismissed || st[step]) return;
  st[step] = true;
  localStorage.setItem(OB_KEY, JSON.stringify(st));
  renderOnboarding();
}
function renderOnboarding() {
  const box = $("onboarding");
  if (!box) return;
  const st = obState();
  const allDone = st.video && st.review && st.export;
  box.style.display = (st.dismissed || allDone || !AppState.user) ? "none" : "block";
  document.querySelectorAll(".ob-step").forEach((li) => {
    const done = !!st[li.dataset.step];
    li.style.opacity = done ? ".55" : "1";
    li.style.borderColor = done ? "var(--color-accent)" : "var(--glass-border)";
    li.querySelector("b").textContent = done ? "✓" : li.dataset.step === "video" ? "1." : li.dataset.step === "review" ? "2." : "3.";
  });
}

function renderPublish() {
  const status = $("publish-status");
  const connectBtn = $("connect-yt-btn");
  if (!status || !connectBtn) return;
  const accounts = AppState.publish.accounts || [];
  const yt = accounts.find((a) => a.provider === "youtube");
  if (!AppState.publish.enabled) {
    status.textContent = "Publishing: not configured";
    connectBtn.classList.add("hidden");
  } else if (yt) {
    status.textContent = `Publishing: connected${yt.accountLabel ? " · " + yt.accountLabel : ""}`;
    connectBtn.classList.add("hidden");
  } else {
    status.textContent = "Publishing: not connected";
    connectBtn.classList.remove("hidden");
  }
}

// --- data loaders ---
async function loadMe() {
  // SWR: hydrate instantly from the persisted cache, then revalidate. A page
  // refresh never logs the user out or renders cold — the httpOnly session
  // cookie is verified by the background /me call.
  const cached = Cache.get("me");
  if (cached.data && !AppState.user) {
    AppState.user = cached.data;
    renderUser();
    renderOnboarding();
  }
  try {
    AppState.user = await api("/api/auth/me");
    Cache.set("me", AppState.user);
  } catch {
    AppState.user = null;
    Cache.invalidate("me", "clips", "publish", "referrals");
  }
  renderUser();
  if (AppState.user) {
    await refreshJobs();
    await loadPublish();
    await loadClips(true);
    await loadAnalytics(false);
    await loadReferrals();
    renderOnboarding();
    await loadSample();
  }
}

// --- Clip library (paginated, score-first) ---
function librarySkeleton() {
  const box = $("clip-library");
  if (!box) return;
  box.innerHTML = Array.from({ length: 4 }).map(() =>
    `<div class="glass" style="padding:10px; border-radius:12px" aria-hidden="true">
       <div style="aspect-ratio:9/16; border-radius:8px; background:linear-gradient(110deg, rgba(255,255,255,.05) 30%, rgba(255,255,255,.12) 50%, rgba(255,255,255,.05) 70%); background-size:200% 100%; animation:shimmer 1.2s linear infinite"></div>
     </div>`).join("");
}

async function loadClips(reset = false) {
  if (reset) {
    AppState.clipsOffset = 0;
    // SWR: cached first page renders instantly; skeleton only on a cold cache.
    const cached = Cache.get("clips");
    if (cached.data) {
      AppState.clipsTotal = cached.data.total;
      renderClipLibrary(cached.data.items, false);
      if (cached.fresh) { AppState.clipsOffset = cached.data.items.length; return finishClipChrome(); }
    } else {
      librarySkeleton();
    }
  }
  let data;
  try {
    data = await api(`/api/clips?limit=${CLIPS_PAGE}&offset=${AppState.clipsOffset}`);
  } catch (e) {
    toast(`Could not load your clips: ${e.message}`, "err");
    const box = $("clip-library");
    if (box && reset && !Cache.get("clips").data) {
      box.innerHTML = '<p class="faint">Could not load clips — try refreshing.</p>';
    }
    return;
  }
  if (reset) Cache.set("clips", data);
  AppState.clipsTotal = data.total;
  renderClipLibrary(data.items, !reset);
  AppState.clipsOffset += data.items.length;
  finishClipChrome();
}

function finishClipChrome() {
  const more = $("load-more-clips");
  if (more) more.classList.toggle("hidden", AppState.clipsOffset >= AppState.clipsTotal);
  const total = $("clips-total");
  if (total) total.textContent = AppState.clipsTotal ? `${AppState.clipsTotal} clip(s) · best first` : "";
}

const ASPECT_CSS = { "9:16": "9/16", "3:4": "3/4", "1:1": "1/1" };

function renderClipLibrary(items, append) {
  const box = $("clip-library");
  if (!box) return;
  if (!append) box.innerHTML = "";
  if (!items.length && !append) {
    box.innerHTML = '<p class="faint">Your rendered clips will appear here.</p>';
    return;
  }
  for (const c of items) {
    const src = c.source && c.source.kind === "youtube" ? "YouTube" : "Upload";
    const when = c.createdAt ? new Date(c.createdAt).toLocaleDateString() : "";
    const ar = ASPECT_CSS[c.aspect] || "9/16";
    const dur = c.duration ? `${Math.round(c.duration)}s` : "";
    const media = c.thumbUrl
      ? `<div style="position:relative"><img src="${c.thumbUrl}" alt="${c.title} thumbnail" loading="lazy" style="width:100%; aspect-ratio:${ar}; object-fit:cover; background:#000; border-radius:8px" />` +
        `<span style="position:absolute; right:8px; bottom:8px; font-size:11px; font-weight:800; background:rgba(0,0,0,.65); color:#fff; padding:2px 8px; border-radius:999px">${dur}</span>` +
        `<span style="position:absolute; left:8px; top:8px; font-size:11px; font-weight:800; background:var(--color-accent); color:#000; padding:2px 8px; border-radius:999px">★ ${Number(c.score).toFixed(2)}</span></div>`
      : `<video src="${c.fileUrl}" preload="metadata" playsinline style="width:100%; aspect-ratio:${ar}; background:#000; border-radius:8px"></video>`;
    const card = document.createElement("div");
    card.className = "glass";
    card.style.cssText = "padding:10px; border-radius:12px; cursor:pointer";
    card.setAttribute("data-action", "open-clip");
    card.setAttribute("data-clip", c.id);
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label", `Open clip: ${c.title}`);
    card.innerHTML = media +
      `<div class="row" style="justify-content:space-between; align-items:center; margin-top:8px; gap:8px">` +
      `<span class="faint" style="font-size:12px">${src} · ${when}</span>` +
      `<span class="row" style="gap:6px">` +
      `<button class="btn" data-action="toggle-feature" data-clip="${c.id}" data-on="${c.featured}" ` +
      `data-tip="Show this clip on the public homepage" style="min-height:36px; padding:6px 10px; font-size:11px">${c.featured ? "★ featured" : "☆ feature"}</button>` +
      `<a class="btn" href="${c.downloadUrl}" data-action="download" data-tip="Download the MP4" download style="min-height:36px; padding:6px 12px">↓</a></span></div>`;
    box.appendChild(card);
  }
}

// Open a library clip in the player pane with full metadata.
async function openClipDetail(clipId) {
  let c;
  try { c = await api(`/api/clips/${clipId}`); }
  catch (e) { toast(e.message, "err"); return; }
  AppState.clip = c;
  renderClip();
  const pane = $("clip-box");
  if (pane) pane.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// --- Referrals: my link, statuses, credits earned ---
async function loadReferrals() {
  const box = $("referral-body");
  if (!box) return;
  const cached = Cache.get("referrals");
  if (cached.data) { AppState.referrals = cached.data; renderReferrals(); if (cached.fresh) return; }
  else box.innerHTML = '<div style="height:56px; border-radius:10px; background:linear-gradient(110deg, rgba(255,255,255,.05) 30%, rgba(255,255,255,.12) 50%, rgba(255,255,255,.05) 70%); background-size:200% 100%; animation:shimmer 1.2s linear infinite" aria-hidden="true"></div>';
  try {
    AppState.referrals = await api("/api/referrals");
    Cache.set("referrals", AppState.referrals);
  } catch (e) {
    box.innerHTML = `<p class="faint">Could not load referrals: ${e.message}</p>`;
    return;
  }
  renderReferrals();
}

function renderReferrals() {
  const box = $("referral-body");
  const r = AppState.referrals;
  if (!box || !r) return;
  const rows = (r.referrals || []).map((x) => {
    const status = x.status === "credited"
      ? `<span class="status-tag status-completed">credited</span>`
      : `<span class="status-tag status-queued">pending</span>`;
    return `<div class="row" style="justify-content:space-between; padding:8px 0; border-top:1px solid var(--glass-border); font-size:13px">` +
           `<span>${x.email}</span>${status}<span>${x.creditsEarned ? "+" + x.creditsEarned : "—"}</span></div>`;
  }).join("");
  box.innerHTML =
    `<div class="row" style="gap:8px; flex-wrap:wrap; align-items:center">` +
    `<input id="referral-link" readonly value="${r.link}" aria-label="Your referral link" ` +
    `style="flex:1; min-width:200px; min-height:44px; padding:8px 12px; border-radius:10px; border:1px solid var(--glass-border); background:rgba(255,255,255,.03); color:var(--color-text); font-size:13px" />` +
    `<button class="btn btn-accent" data-action="copy-referral" data-tip="Copy your invite link" style="min-height:44px">Copy link</button></div>` +
    `<p class="faint" style="font-size:12px; margin:10px 0 0">1. Share your link · 2. A friend signs up · 3. When they buy any plan you get <b style="color:var(--color-accent-hot)">+${r.rewards.referrer}</b> credits and they get <b style="color:var(--color-accent-hot)">+${r.rewards.referred}</b>.</p>` +
    (rows
      ? `<div style="margin-top:12px">${rows}</div>` +
        `<p style="font-size:13px; margin-top:10px">Total earned: <b style="color:var(--color-accent-hot)">${r.totalEarned} credits</b></p>`
      : `<p class="faint" style="font-size:13px; margin-top:12px">No referrals yet — your link is ready to share.</p>`);
}

// --- Feature C: connected-channel analytics ---
async function loadAnalytics(force) {
  const body = $("analytics-body");
  const updated = $("analytics-updated");
  if (!body) return;
  let a;
  try { a = await api(`/api/publish/analytics${force ? "?force=true" : ""}`); }
  catch (e) {
    body.innerHTML = e.code === "deferred"
      ? "Analytics enable once publishing is configured."
      : `Could not load analytics: ${e.message}`;
    return;
  }
  if (!a.connected) { body.textContent = "Connect YouTube to see analytics for your channel."; if (updated) updated.textContent = ""; return; }
  if (a.needsReconnect) {
    body.innerHTML = `${a.reason || "Reconnect required."} ` +
      `<button class="btn" data-action="connect-youtube" style="margin-left:8px">Reconnect YouTube</button>`;
    if (updated) updated.textContent = "";
    return;
  }
  if (updated) updated.textContent = a.lastUpdated
    ? `updated ${new Date(a.lastUpdated).toLocaleTimeString()}${a.stale ? " (cached)" : ""}` : "";
  if (!a.channels || !a.channels.length) { body.textContent = "No channel data yet."; return; }
  body.classList.remove("faint");
  body.innerHTML = a.channels.map((ch) => {
    const l = ch.last28 || {};
    const stat = (label, val) =>
      `<div style="flex:1; min-width:110px"><div class="faint" style="font-size:12px">${label}</div>` +
      `<div style="font-size:20px; font-weight:700">${(val ?? 0).toLocaleString()}</div></div>`;
    return `<div style="margin-top:6px"><b>${ch.title || "Channel"}</b>` +
      `<div class="row" style="gap:14px; flex-wrap:wrap; margin-top:8px">` +
      stat("Subscribers", ch.subscribers) + stat("Total views", ch.totalViews) +
      stat("Views (28d)", l.views) + stat("Likes (28d)", l.likes) +
      stat("Watch min (28d)", l.minutesWatched) + `</div></div>`;
  }).join("");
}

async function loadPublish() {
  try {
    const data = await api("/api/publish/providers");
    const yt = (data.providers || []).find((p) => p.key === "youtube");
    AppState.publish = { enabled: !!(yt && yt.enabled), accounts: data.accounts || [] };
  } catch { AppState.publish = { enabled: false, accounts: [] }; }
  renderPublish();
}

async function refreshJobs() {
  AppState.jobs = await api("/api/jobs");
  renderJobs();
}

// --- Optimistic processing card: appears in the library the instant a job is
// submitted, driven by SSE stages 0-6 (frozen labels) + elapsed time. ---
function renderOptimisticCard() {
  const box = $("clip-library");
  if (!box) return;
  let card = $("optimistic-card");
  const job = AppState.optimisticJob;
  if (!job) { if (card) card.remove(); return; }
  if (!card) {
    card = document.createElement("div");
    card.id = "optimistic-card";
    card.className = "glass";
    card.style.cssText =
      "padding:10px; border-radius:12px; border:1px solid var(--color-accent); " +
      "animation: obpulse 1.6s ease-in-out infinite";
    const first = box.firstChild;
    box.insertBefore(card, first);
  }
  const elapsed = Math.round((Date.now() - job.startedAt) / 1000);
  const pct = Math.round((AppState.progress || 0) * 100);
  const label = job.failed
    ? `<b style="color:var(--color-error)">Failed</b> — ${job.error || "pipeline error"}`
    : job.stalled
      ? "Still working… (no update for a bit — hang tight)"
      : `${STEP_LABELS[AppState.stage] || "Queued"}`;
  card.innerHTML =
    `<div style="aspect-ratio:9/16; border-radius:8px; background:var(--color-surface-3); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; padding:12px; text-align:center">` +
    (job.failed
      ? `<div style="font-size:26px" aria-hidden="true">⚠️</div>` +
        `<div style="font-size:13px">${label}</div>` +
        `<button class="btn btn-accent" data-action="retry-job" data-tip="Run this video again" style="min-height:40px">Retry</button>`
      : `<div class="bar" style="width:80%"><i style="width:${pct}%"></i></div>` +
        `<div style="font-size:13px" aria-live="polite">${label}</div>` +
        `<div class="faint" style="font-size:11px">${elapsed}s elapsed · ${pct}%</div>`) +
    `</div>`;
}

// --- SSE: stages 0 -> 6, heartbeat-aware with resume-on-drop ---
function connectStream(jobId) {
  if (AppState.sse) AppState.sse.close();
  if (AppState.heartbeat) clearInterval(AppState.heartbeat);
  AppState.activeJobId = jobId;
  AppState.lastEventAt = Date.now();

  const open = () => {
    const es = new EventSource(`/api/stream/${jobId}`);
    AppState.sse = es;
    es.onmessage = async (ev) => {
      let p; try { p = JSON.parse(ev.data); } catch { return; }
      AppState.lastEventAt = Date.now();
      if (AppState.optimisticJob) { AppState.optimisticJob.stalled = false; }
      AppState.stage = p.stage;
      AppState.progress = p.progress;
      renderStepper();
      renderOptimisticCard();
      if (p.status === "completed") {
        es.close(); AppState.sse = null;
        clearInterval(AppState.heartbeat);
        AppState.optimisticJob = null;
        renderOptimisticCard();
        toast("Clips ready!", "ok");
        Cache.invalidate("clips", "me");  // exact keys, never a blanket wipe
        await openJob(jobId);
        await loadMe();  // credits reconcile from the SERVER, never client math
      } else if (p.status === "failed") {
        es.close(); AppState.sse = null;
        clearInterval(AppState.heartbeat);
        if (AppState.optimisticJob) {
          AppState.optimisticJob.failed = true;
          AppState.optimisticJob.error = p.message;
          renderOptimisticCard();
        }
        toast(`Pipeline failed: ${p.message}`, "err");
        Cache.invalidate("clips", "me");
        await refreshJobs();
      }
    };
    es.onerror = () => {
      // Browser auto-retries; if the stream is hard-closed, reconnect and
      // resume from the last known stage rather than resetting to 0.
      if (es.readyState === EventSource.CLOSED && AppState.activeJobId === jobId) {
        setTimeout(() => { if (AppState.activeJobId === jobId) open(); }, 2000);
      }
    };
  };
  open();

  // Heartbeat: no event for 20s -> "still working…" on the optimistic card.
  AppState.heartbeat = setInterval(() => {
    if (AppState.optimisticJob && !AppState.optimisticJob.failed
        && Date.now() - AppState.lastEventAt > 20_000) {
      AppState.optimisticJob.stalled = true;
      renderOptimisticCard();
    }
  }, 5000);
}

async function openJob(jobId) {
  const job = await api(`/api/jobs/${jobId}`);
  AppState.stage = job.stage;
  AppState.progress = job.progress;
  renderStepper();
  if (job.clips && job.clips.length) {
    const c = job.clips[0];
    AppState.clip = {
      id: c.id, title: c.title, score: c.score, signals: c.signals,
      fileUrl: `/api/clips/${c.id}/file`, downloadUrl: `/api/clips/${c.id}/download`,
    };
    renderClip();
  } else if (job.status === "running" || job.status === "queued") {
    connectStream(jobId);
  }
  await refreshJobs();
}

// --- actions ---
const actions = {
  async login() {
    const body = new FormData();
    body.append("email", $("login-email").value);
    body.append("password", $("login-password").value);
    try {
      AppState.user = await api("/api/auth/login", { method: "POST", body });
      renderUser();
      await refreshJobs();
      toast("Signed in", "ok");
    } catch (e) { toast(e.message, "err"); }
  },

  async logout() {
    await api("/api/auth/logout", { method: "POST" });
    AppState.user = null; AppState.jobs = []; AppState.clip = null;
    if (AppState.sse) { AppState.sse.close(); AppState.sse = null; }
    renderUser();
  },

  "choose-file"() { $("file-input").click(); },

  async upload() {
    if (!AppState.file) { toast("Choose an MP4 first", "err"); return; }
    const body = new FormData();
    body.append("file", AppState.file);
    $("upload-btn").disabled = true;
    AppState.clip = null; renderClip();
    AppState.stage = 0; AppState.progress = 0; renderStepper();
    try {
      const job = await api("/api/jobs", { method: "POST", body });
      toast("Uploaded — finding your best moments", "ok");
      markOnboarding("video");
      AppState.lastSubmit = { type: "file" };
      AppState.optimisticJob = { startedAt: Date.now() };
      renderOptimisticCard();
      connectStream(job.id);
      await refreshJobs();
      await loadMe();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      $("upload-btn").disabled = false;
    }
  },

  async "submit-url"() {
    const input = $("url-input");
    const url = (input.value || "").trim();
    if (!url) { toast("Paste a YouTube URL first", "err"); return; }
    const btn = $("url-btn");
    if (btn) btn.disabled = true;
    AppState.clip = null; renderClip();
    AppState.stage = 0; AppState.progress = 0; renderStepper();
    try {
      const body = new FormData();
      body.append("url", url);
      const job = await api("/api/jobs", { method: "POST", body });
      toast("Link accepted — cutting your top moments", "ok");
      markOnboarding("video");
      AppState.lastSubmit = { type: "url", url };
      AppState.optimisticJob = { startedAt: Date.now() };
      renderOptimisticCard();
      input.value = "";
      connectStream(job.id);
      await refreshJobs();
      await loadMe();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async "open-job"(el) { await openJob(el.dataset.job); },

  async "open-clip"(el) { await openClipDetail(el.dataset.clip); },

  async "billing-portal"() {
    try {
      const data = await api("/api/billing/portal", { method: "POST" });
      if (data && data.url) { window.location.href = data.url; }
    } catch (e) {
      toast(e.code === "deferred" ? "Billing isn't enabled yet." : e.message, "err");
    }
  },

  async "connect-youtube"() {
    try {
      const data = await api("/api/publish/youtube/connect");
      if (data && data.url) { window.location.href = data.url; }
    } catch (e) {
      toast(e.code === "deferred" ? "Publishing isn't enabled yet." : e.message, "err");
    }
  },

  async "publish-clip"() {
    if (!AppState.clip) { toast("Generate a clip first", "err"); return; }
    const btn = $("publish-btn");
    if (btn) btn.disabled = true;
    try {
      const data = await api(`/api/publish/${AppState.clip.id}`, { method: "POST" });
      toast(`Published privately to YouTube${data.url ? " · " + data.url : ""}`, "ok");
    } catch (e) {
      if (e.code === "deferred") toast("Publishing isn't enabled yet.", "err");
      else if (e.code === "not_connected") { toast("Connect a YouTube account first.", "err"); await loadPublish(); }
      else toast(e.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async "load-more-clips"() { await loadClips(false); },

  async "refresh-analytics"() {
    const btn = $("analytics-refresh");
    if (btn) btn.disabled = true;
    try { await loadAnalytics(true); } finally { if (btn) btn.disabled = false; }
  },

  async "retry-job"() {
    const last = AppState.lastSubmit;
    AppState.optimisticJob = null;
    renderOptimisticCard();
    if (last && last.type === "url" && last.url) {
      $("url-input").value = last.url;
      await actions["submit-url"]();
    } else if (last && last.type === "file" && AppState.file) {
      await actions.upload();
    } else {
      toast("Re-select your video to retry.", "err");
    }
  },

  async "copy-referral"() {
    const input = $("referral-link");
    if (!input) return;
    try {
      await navigator.clipboard.writeText(input.value);
      toast("Invite link copied — go earn credits!", "ok");
    } catch (_) {
      input.select();
      document.execCommand("copy");
      toast("Invite link copied", "ok");
    }
  },

  async "toggle-feature"(el) {
    // Optimistic star flip; server response reconciles, error rolls back.
    const id = el.dataset.clip;
    const want = el.dataset.on !== "true";
    el.dataset.on = String(want);
    el.textContent = want ? "★ featured" : "☆ feature";
    try {
      const body = new FormData();
      body.append("on", want);
      const res = await api(`/api/clips/${id}/feature`, { method: "POST", body });
      Cache.invalidate("clips");
      toast(res.featured ? "On the public homepage now." : "Removed from the homepage.", "ok");
    } catch (e) {
      el.dataset.on = String(!want);  // roll back
      el.textContent = !want ? "★ featured" : "☆ feature";
      toast(e.message, "err");
    }
  },

  "dismiss-onboarding"() {
    const st = obState();
    st.dismissed = true;
    localStorage.setItem(OB_KEY, JSON.stringify(st));
    renderOnboarding();
  },

  download() { markOnboarding("export"); /* href on the anchor handles the actual download */ },
};

// --- the single delegated click switch ---
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el) return;
  const action = el.dataset.action;
  if (action in actions) {
    if (action !== "download") e.preventDefault();
    actions[action](el);
  }
});

// Keyboard activation for non-native buttons (dropzone, job rows).
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const el = e.target.closest('[data-action][role="button"]');
  if (!el) return;
  e.preventDefault();
  const action = el.dataset.action;
  if (action in actions) actions[action](el);
});

// file input change -> stash file
document.addEventListener("change", (e) => {
  if (e.target.id !== "file-input") return;
  AppState.file = e.target.files[0] || null;
  $("filename").textContent = AppState.file ? AppState.file.name : "No file selected";
  $("upload-btn").disabled = !AppState.file;
});

// OAuth connect round-trip feedback (?connect=youtube&ok=1 | &error=...)
function showConnectFeedback() {
  const q = new URLSearchParams(window.location.search);
  if (q.get("connect") !== "youtube") return;
  if (q.get("ok")) toast("YouTube connected — clips publish privately.", "ok");
  else if (q.get("error")) toast(`Couldn't connect YouTube (${q.get("error")}).`, "err");
  // Strip the params so a refresh doesn't re-toast.
  window.history.replaceState({}, "", window.location.pathname);
}

// boot
renderStepper();
showConnectFeedback();
loadMe();
