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
};

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
  $("progbar").style.width = `${Math.round(AppState.progress * 100)}%`;
}

function renderJobs() {
  const el = $("joblist");
  if (!AppState.jobs.length) { el.innerHTML = `<p class="faint">No jobs yet.</p>`; return; }
  el.innerHTML = AppState.jobs.map((j) => `
    <div class="jobrow" data-action="open-job" data-job="${j.id}">
      <div><div>Job ${j.id.slice(0, 8)}</div>
        <div class="faint" style="font-size:12px">stage ${j.stage}/6</div></div>
      <span class="status-tag status-${j.status}">${j.status}</span>
    </div>`).join("");
}

function renderClip() {
  const has = !!AppState.clip;
  $("clip-empty").classList.toggle("hidden", has);
  $("clip-box").classList.toggle("hidden", !has);
  if (!has) return;
  const c = AppState.clip;
  $("clip-video").src = c.fileUrl;
  $("clip-score").textContent = `score ${(c.score ?? 0).toFixed(3)}`;
  $("download-link").href = c.downloadUrl;
  const s = c.signals || {};
  $("clip-signals").innerHTML = `
    <div><b>${(s.hook ?? 0).toFixed(2)}</b>hook</div>
    <div><b>${(s.pace ?? 0).toFixed(2)}</b>pace</div>
    <div><b>${(s.sentiment ?? 0).toFixed(2)}</b>sentiment</div>
    <div><b>${(s.face ?? 0).toFixed(2)}</b>face</div>`;
}

// --- data loaders ---
async function loadMe() {
  try { AppState.user = await api("/api/auth/me"); }
  catch { AppState.user = null; }
  renderUser();
  if (AppState.user) await refreshJobs();
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
      toast("Uploaded — processing started", "ok");
      connectStream(job.id);
      await refreshJobs();
      await loadMe();
    } catch (e) {
      toast(e.message, "err");
    } finally {
      $("upload-btn").disabled = false;
    }
  },

  async "open-job"(el) { await openJob(el.dataset.job); },

  async "billing-portal"() {
    try {
      const data = await api("/api/billing/portal", { method: "POST" });
      if (data && data.url) { window.location.href = data.url; }
    } catch (e) {
      toast(e.code === "deferred" ? "Billing isn't enabled yet." : e.message, "err");
    }
  },

  download() { /* href on the anchor handles the actual download */ },
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

// file input change -> stash file
document.addEventListener("change", (e) => {
  if (e.target.id !== "file-input") return;
  AppState.file = e.target.files[0] || null;
  $("filename").textContent = AppState.file ? AppState.file.name : "No file selected";
  $("upload-btn").disabled = !AppState.file;
});

// boot
renderStepper();
loadMe();
