/* ── AiSongTool frontend ──────────────────────────────────────────── */

let currentJob     = null;
let statusTimer    = null;
let logTimer       = null;
let autoDownloaded = false;
let logVisible     = true;

const $ = id => document.getElementById(id);

/* ── Settings persistence ───────────────────────────────────────────── */

const SETTINGS_KEY = "aisongtool_settings";

function saveSettings() {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify({
      model:       $("model")       ? $("model").value            : "large-v3",
      language:    $("language")    ? $("language").value         : "",
      cue_mode:    $("cue_mode")    ? $("cue_mode").value         : "line",
      vad:         $("vad")         ? $("vad").value              : "silero",
      skip_demucs: $("skip_demucs") ? $("skip_demucs").checked    : false,
    }));
  } catch (e) { /* ignore */ }
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return;
    const s = JSON.parse(raw);
    if (s.model       != null && $("model"))       $("model").value          = s.model;
    if (s.language    != null && $("language"))    $("language").value       = s.language;
    if (s.cue_mode    != null && $("cue_mode"))    $("cue_mode").value       = s.cue_mode;
    if (s.vad         != null && $("vad"))         $("vad").value            = s.vad;
    if (s.skip_demucs != null && $("skip_demucs")) $("skip_demucs").checked  = s.skip_demucs;
  } catch (e) { /* ignore */ }
}

/* ── GPU badge ──────────────────────────────────────────────────────── */

async function fetchGpuInfo() {
  try {
    const res = await fetch("/gpu-info", { cache: "no-store" });
    if (!res.ok) return;
    const info = await res.json();
    const dot = $("gpuDot"), text = $("gpuText"), badge = $("gpuBadge");
    if (!dot || !text) return;

    if (info.available) {
      dot.className = "gpu-dot on";
      let label = info.name || "GPU";
      if (info.mem_gb) label += " · " + info.mem_gb;
      const util = parseInt(info.util_pct) || 0;
      if (util > 5) {
        label += " · " + info.util_pct + "%";
        if (info.temp_c) label += " · " + info.temp_c + "°C";
      }
      text.textContent = label;
      if (badge && info.driver) badge.title = "Driver: " + info.driver;
    } else {
      dot.className = "gpu-dot off";
      text.textContent = "CPU only";
      if (badge) badge.title = "No NVIDIA GPU detected";
    }
  } catch (e) { /* ignore */ }
}

/* ── Progress helpers ───────────────────────────────────────────────── */

function setProgress(pct, activeStep) {
  const fill = $("progressFill");
  const pctEl = $("progressPct");
  if (fill)  fill.style.width  = Math.min(100, Math.max(0, pct)) + "%";
  if (pctEl) pctEl.textContent = Math.round(pct) + "%";

  if (activeStep === undefined || activeStep === null || activeStep < 0) return;

  for (let i = 0; i < 3; i++) {
    const el = $("step" + i);
    if (!el) continue;
    if (activeStep >= 3) {
      el.className = "jstep done";
    } else if (i < activeStep) {
      el.className = "jstep done";
    } else if (i === activeStep) {
      el.className = "jstep active";
    } else {
      el.className = "jstep";
    }
  }
}

function setStatusBadge(text, cls) {
  const el = $("statusBadge");
  if (!el) return;
  el.textContent = text;
  el.className   = "status-badge" + (cls ? " " + cls : "");
}

/* ── Parse log for step progress ────────────────────────────────────── */

function updateProgressFromLog(logText) {
  if (!logText) return;
  const has = s => logText.includes(s);

  let activeStep = 0;
  let pct = 12;

  if (has("DONE")) {
    pct = 94; activeStep = 2;
  } else if (has("Step 3:") || has("Step 4:") || has("Step 5:")) {
    pct = 82; activeStep = 2;
  } else if (has("[INFO] Wrote") || (has("Wrote:") && has("whisperx.json"))) {
    pct = 75; activeStep = 2;
  } else if (has("Align language")) {
    pct = 68; activeStep = 1;
  } else if (has("Performing voice activity")) {
    pct = 55; activeStep = 1;
  } else if (has("Step 2:")) {
    pct = 46; activeStep = 1;
  } else if (has("[demucs] done") || has("Demucs skipped")) {
    pct = 40; activeStep = 1;
  } else if (has("Step 1:")) {
    activeStep = 0;
    const re = /(\d+)%\|/g;
    let m, lastN = null;
    while ((m = re.exec(logText)) !== null) lastN = parseInt(m[1]);
    if (lastN !== null && !isNaN(lastN)) {
      pct = 14 + Math.round(lastN * 0.25);
    } else {
      pct = 16;
    }
  }

  setProgress(pct, activeStep);
}

/* ── Log viewer polling ─────────────────────────────────────────────── */

async function pollLog() {
  try {
    const res = await fetch("/log/tail?lines=300", { cache: "no-store" });
    if (!res.ok) return;
    const text = await res.text();
    const viewer = $("logViewer");
    if (!viewer) return;
    const atBottom = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 40;
    viewer.textContent = text;
    if (atBottom) viewer.scrollTop = viewer.scrollHeight;
    updateProgressFromLog(text);
  } catch (e) { /* ignore */ }
}

function startLogPolling() {
  if (logTimer) clearInterval(logTimer);
  pollLog();
  logTimer = setInterval(pollLog, 1500);
}

function stopLogPolling(skipFinal = false) {
  if (logTimer) { clearInterval(logTimer); logTimer = null; }
  if (!skipFinal) pollLog();
}

/* ── File helpers ───────────────────────────────────────────────────── */

function fmtBytes(n) {
  if (n < 1024)          return n + " B";
  if (n < 1024 * 1024)   return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function showFile(file) {
  $("dropZone").classList.add("has-file");
  const info = $("fileInfo");
  if (info) {
    info.classList.add("visible");
    $("fileName").textContent = file.name;
    $("fileSize").textContent = fmtBytes(file.size);
  }
}

function clearFile() {
  $("dropZone").classList.remove("has-file");
  const info = $("fileInfo");
  if (info) info.classList.remove("visible");
}

/* ── Form lock ──────────────────────────────────────────────────────── */

function setFormLocked(locked) {
  ["song", "lyrics", "fmt", "model", "language", "cue_mode", "vad", "skip_demucs"].forEach(id => {
    const el = $(id); if (el) el.disabled = locked;
  });
  const btn = $("startBtn");
  if (btn) btn.disabled = locked;
  const stop = $("stopBtn");
  if (stop) stop.style.display = locked ? "inline-flex" : "none";
}

/* ── Stop job ───────────────────────────────────────────────────────── */

async function stopJob() {
  try {
    await fetch("/stop", { method: "POST", cache: "no-store" });
  } catch (e) { /* ignore */ }
  clearInterval(statusTimer); statusTimer = null;
  stopLogPolling();
  setStatusBadge("cancelled", "failed");
  setFormLocked(false);
}

/* ── Status polling ─────────────────────────────────────────────────── */

function selectedFormat() { return $("fmt") ? $("fmt").value : "srt"; }
function dlUrl(jobId, fmt) { return `/job/${jobId}/download/${fmt}`; }

async function pollStatus() {
  if (!currentJob) return;
  try {
    const res = await fetch(`/job/${currentJob}/status`, { cache: "no-store" });
    if (!res.ok) return;
    const st = await res.json();

    if (st.status === "running") {
      setStatusBadge("running…", "");
      return;
    }

    if (st.status === "done") {
      clearInterval(statusTimer); statusTimer = null;
      setStatusBadge("done", "done");
      setProgress(100, 3);
      setFormLocked(false);
      stopLogPolling();
      renderResults();
      if (!autoDownloaded) {
        autoDownloaded = true;
        window.location.href = dlUrl(currentJob, selectedFormat());
      }
      return;
    }

    if (st.status === "failed") {
      clearInterval(statusTimer); statusTimer = null;
      setStatusBadge("failed", "failed");
      setFormLocked(false);
      stopLogPolling();
      return;
    }

  } catch (e) { /* network error — keep polling */ }
}

/* ── Results panel ──────────────────────────────────────────────────── */

function renderResults() {
  const fmt = selectedFormat();
  const grid = $("downloadGrid");
  if (!grid) return;

  const formats = [
    { id: "srt",    label: "SRT",    hint: "CapCut · Premiere · DaVinci" },
    { id: "ass",    label: "ASS",    hint: "Advanced SubStation" },
    { id: "vtt",    label: "VTT",    hint: "Web / browser" },
    { id: "lrc",    label: "LRC",    hint: "Lyrics players" },
    { id: "sbv",    label: "SBV",    hint: "YouTube Studio" },
    { id: "zip",    label: "ZIP",    hint: "All formats" },
    { id: "lyrics", label: "Lyrics", hint: "Clean .txt" },
  ];

  grid.innerHTML = formats.map(f => {
    const isPrimary = f.id === fmt;
    const cls = isPrimary ? "btn btn-primary" : "btn btn-success";
    return `<a class="${cls}" href="${dlUrl(currentJob, f.id)}" title="${f.hint}">${f.label}</a>`;
  }).join("");

  const card = $("resultsCard");
  if (card) {
    card.style.display = "block";
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

/* ── Clear / reset ──────────────────────────────────────────────────── */

function clearForm() {
  autoDownloaded = false;
  currentJob = null;
  if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
  stopLogPolling(true);
  setFormLocked(false);
  clearFile();

  $("progressCard").style.display = "none";
  $("resultsCard").style.display  = "none";
  $("jobId").textContent          = "—";
  $("logViewer").textContent      = "";

  for (let i = 0; i < 3; i++) {
    const el = $("step" + i); if (el) el.className = "jstep";
  }
  setProgress(0);
  setStatusBadge("—", "");

  $("jobForm").reset();
  $("song").value = "";
  $("formNote").textContent = "";

  // Restore saved settings after reset (reset clears them)
  loadSettings();
}

/* ── Init ─────────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", () => {

  // Load persisted settings
  loadSettings();

  // GPU badge — immediate + 8 s refresh
  fetchGpuInfo();
  setInterval(fetchGpuInfo, 8000);

  // Save settings whenever any advanced option changes
  ["model", "language", "cue_mode", "vad", "skip_demucs"].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener("change", saveSettings);
  });

  // Stop button hidden by default
  const stopBtn = $("stopBtn");
  if (stopBtn) {
    stopBtn.style.display = "none";
    stopBtn.addEventListener("click", stopJob);
  }

  // Log toggle
  const toggleBtn = $("logToggleBtn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      logVisible = !logVisible;
      $("logViewer").classList.toggle("collapsed", !logVisible);
      toggleBtn.textContent = logVisible ? "Hide" : "Show";
    });
  }

  $("clearBtn").addEventListener("click", clearForm);
  $("newJobBtn").addEventListener("click", clearForm);

  /* ── Drag & drop ──────────────────────────────────────────────────── */

  const dropZone  = $("dropZone");
  const fileInput = $("song");

  if (dropZone) {
    dropZone.addEventListener("click", () => fileInput.click());
    dropZone.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
    });

    dropZone.addEventListener("dragover", e => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragleave", e => {
      if (!dropZone.contains(e.relatedTarget))
        dropZone.classList.remove("drag-over");
    });

    dropZone.addEventListener("drop", e => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
      const file = e.dataTransfer && e.dataTransfer.files[0];
      if (!file) return;
      try {
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
      } catch (_) { /* Safari fallback */ }
      showFile(file);
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) showFile(fileInput.files[0]);
      else clearFile();
    });
  }

  /* ── Form submit ──────────────────────────────────────────────────── */

  $("jobForm").addEventListener("submit", async e => {
    e.preventDefault();
    $("formNote").textContent = "";

    const song   = fileInput.files && fileInput.files[0];
    const lyrics = $("lyrics").value.trim();

    if (!song) { $("formNote").textContent = "Please choose an audio file."; return; }

    saveSettings();
    autoDownloaded = false;
    setFormLocked(true);

    $("progressCard").style.display = "block";
    $("resultsCard").style.display  = "none";
    setStatusBadge("starting…", "");
    setProgress(6, 0);
    $("progressCard").scrollIntoView({ behavior: "smooth", block: "nearest" });

    const fd = new FormData();
    fd.append("song",        song);
    fd.append("lyrics",      lyrics);
    fd.append("model",       ($("model")    ? $("model").value    : "large-v3"));
    fd.append("language",    ($("language") ? $("language").value : ""));
    fd.append("cue_mode",    ($("cue_mode") ? $("cue_mode").value : "line"));
    fd.append("vad",         ($("vad")      ? $("vad").value      : "silero"));
    const skipDemucs = $("skip_demucs");
    if (skipDemucs && skipDemucs.checked) fd.append("skip_demucs", "1");

    try {
      const res = await fetch("/start", { method: "POST", body: fd });

      if (!res.ok) {
        const txt = await res.text();
        $("formNote").textContent = txt || "Failed to start job.";
        setStatusBadge("error", "failed");
        setFormLocked(false);
        return;
      }

      const payload  = await res.json();
      currentJob     = payload.job_id;
      $("jobId").textContent = currentJob;

      setStatusBadge("running…", "");
      setProgress(12, 0);

      if (statusTimer) clearInterval(statusTimer);
      statusTimer = setInterval(pollStatus, 1000);
      pollStatus();
      startLogPolling();

    } catch (err) {
      $("formNote").textContent = "Network error — is the server running?";
      setStatusBadge("error", "failed");
      setFormLocked(false);
    }
  });
});
