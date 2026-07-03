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
      `<a class="btn" href="/#pricing">Upgrade</a>` +
      `<button class="btn" data-action="billing-portal">Billing</button>` +
      `<button class="btn" data-action="logout">Sign out</button>`;
    $("credits").textContent = AppState.user.credits;
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
  try { AppState.user = await api("/api/auth/me"); }
  catch { AppState.user = null; }
  renderUser();
  if (AppState.user) {
    await refreshJobs();
    await loadPublish();
    await loadClips(true);
    await loadAnalytics(false);
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
  if (reset) { AppState.clipsOffset = 0; librarySkeleton(); }
  let data;
  try {
    data = await api(`/api/clips?limit=${CLIPS_PAGE}&offset=${AppState.clipsOffset}`);
  } catch (e) {
    toast(`Could not load your clips: ${e.message}`, "err");
    const box = $("clip-library");
    if (box && reset) box.innerHTML = '<p class="faint">Could not load clips — try refreshing.</p>';
    return;
  }
  AppState.clipsTotal = data.total;
  renderClipLibrary(data.items, !reset);
  AppState.clipsOffset += data.items.length;
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
      `<span class="faint" style="font-size:12px">${src} · ${when}${c.featured ? " · <b style='color:var(--color-accent-hot)'>featured</b>" : ""}</span>` +
      `<a class="btn" href="${c.downloadUrl}" data-action="download" download style="min-height:36px; padding:6px 12px">↓</a></div>`;
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

// --- SSE: stages 0 -> 6 ---
function connectStream(jobId) {
  if (AppState.sse) AppState.sse.close();
  AppState.activeJobId = jobId;
  const es = new EventSource(`/api/stream/${jobId}`);
  AppState.sse = es;
  es.onmessage = async (ev) => {
    let p; try { p = JSON.parse(ev.data); } catch { return; }
    AppState.stage = p.stage;
    AppState.progress = p.progress;
    renderStepper();
    if (p.status === "completed") {
      es.close(); AppState.sse = null;
      toast("Clip ready!", "ok");
      await openJob(jobId);
      await loadMe();
    } else if (p.status === "failed") {
      es.close(); AppState.sse = null;
      toast(`Pipeline failed: ${p.message}`, "err");
      await refreshJobs();
    }
  };
  es.onerror = () => { /* keep-alive gaps are expected; browser auto-retries */ };
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
