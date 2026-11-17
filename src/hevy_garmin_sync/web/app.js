// The status page (spec W-2). It reads /api/status and /api/logs from the app that served it, and asks for a sync
// with POST /api/sync. No framework and no build step: this file is served as it is.
"use strict";

const STEPS = ["Reading Hevy", "Reading Hevy Trainer", "Reading Garmin", "Writing workouts", "Sending to the watch", "Updating today's calendar"];
const CHOSEN = { map: "Exercise map", custom: "<code>CUSTOM_EXERCISE_MAP</code>", guess: "Closest by muscle group and equipment" };
const EXTRA = { "Hevy": "Nothing syncs until then.", "Hevy Trainer": "Routines keep syncing.", "Garmin": "Nothing reaches Garmin until then." };
const REPO = "https://github.com/zimmertr/hevy-garmin-sync";
const LOUD = new Set(["WARNING", "ERROR", "CRITICAL"]); // what "Errors and warnings only" keeps
const EXTERNAL = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M9 3h4v4M13 3L7 9M12 9.5V13H3V4h3.5"/></svg>';

const $ = (selector) => document.querySelector(selector);
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private window: the page works without it */ } },
};

let status = null;
let filter = "all";
let query = "";
let selected = null; // a workout's key
let notice = null; // a reply to a button press, shown until the status moves on: { html, tone, until }
let logLines = [];
let logMore = true;
let logLoaded = false;
let detail = { key: null, html: "" }; // the detail pane as last drawn, so a poll that changes nothing leaves it alone
let started = null; // when the app that answers started: a new value is a new app
let offline = false;

// One time format everywhere, in the app's time zone: "Nov 12, 9:41 AM" (TJ, 2026-11-12).
function when(iso) {
  if (!iso) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: status.time_zone }).format(new Date(iso));
}
function day(isoDate) {
  return isoDate ? new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(isoDate + "T00:00:00Z")) : "";
}
// A log line's time, with seconds: "12:43:16 AM", or "Nov 14, 12:43:16 AM" for Copy log.
function clock(iso, withDay) {
  const parts = { hour: "numeric", minute: "2-digit", second: "2-digit", timeZone: status ? status.time_zone : undefined };
  if (withDay) Object.assign(parts, { month: "short", day: "numeric" });
  return new Intl.DateTimeFormat(undefined, parts).format(new Date(iso));
}
function today() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: status.time_zone }).format(new Date());
}
function codeify(text) {
  // Variable names, the cookie and the command read as code.
  return esc(text).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b|(auth2\.0-token)/g, (m) => `<code>${m}</code>`);
}
// "3 written, 0 deleted", and ", 1 refused" once Garmin refused any: `by` adds " by Garmin" to that.
function counts(c, by = "") {
  if (!c) return "";
  const written = c.created + c.updated;
  return `${written} written, ${c.deleted} deleted${c.failed ? `, ${c.failed} refused${by}` : ""}`;
}

// ---- Data ----

async function refresh() {
  try {
    const reply = await fetch("/api/status", { cache: "no-store" });
    if (!reply.ok) throw new Error(`status ${reply.status}`);
    const next = await reply.json();
    // A new app, maybe a new version: reload, so its page, its log and its workouts all come with it.
    if (started && next.started !== started) { location.reload(); return; }
    started = next.started;
    status = next;
    offline = false;
    render();
  } catch {
    // The app is restarting or out of reach. Keep asking, every second, until it answers.
    offline = true;
    if (status) renderOffline();
  }
  // Folded or not: the folded log's header shows the newest line.
  if (!offline) await newLines();
  setTimeout(refresh, offline || (status && status.sync.state !== "idle") ? 1000 : 5000);
}

async function logPage(before, size) {
  const params = new URLSearchParams({ size: String(size) });
  if (before) params.set("before", String(before));
  const reply = await fetch("/api/logs?" + params, { cache: "no-store" });
  return reply.ok ? reply.json() : { lines: [], more: false };
}

async function newLines() {
  try {
    const page = await logPage(null, 200);
    const last = logLines.length ? logLines[logLines.length - 1].seq : 0;
    const fresh = page.lines.filter((l) => l.seq > last);
    // More than a page was logged since the last poll: start over from the newest page, so no gap hides in the middle.
    const gap = page.lines.length && page.lines[0].seq > last + 1;
    if (!logLoaded || gap) { logMore = page.more; logLoaded = true; }
    if (fresh.length) {
      const box = $("#lines");
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 8;
      logLines = gap ? page.lines : logLines.concat(fresh);
      renderLog();
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
  } catch { /* try again at the next poll */ }
}

async function olderLines() {
  const box = $("#lines");
  const height = box.scrollHeight;
  const page = await logPage(logLines.length ? logLines[0].seq : null, 200);
  logLines = page.lines.concat(logLines);
  logMore = page.more;
  renderLog();
  box.scrollTop = box.scrollHeight - height;
}

async function sync(force) {
  try {
    const reply = await fetch("/api/sync" + (force ? "?force=true" : ""), { method: "POST" });
    const body = await reply.json();
    if (body.result === "wait") {
      notice = { html: `The last sync ended ${60 - body.seconds} seconds ago. You can sync again in ${body.seconds} seconds.`, tone: "wait", until: Date.now() + 4000 };
    } else if (body.result === "refused") {
      notice = { html: `No sync can run: ${codeify(body.reason)}`, tone: "bad", until: Date.now() + 4000 };
    } else if (body.result === "joined" && body.running) {
      notice = { html: "A sync is already running. Your request joined it.", tone: "blue", until: Date.now() + 4000 };
    } else {
      notice = null;
    }
  } catch {
    notice = { html: "The app didn't answer. Try again in a moment.", tone: "bad", until: Date.now() + 4000 };
  }
  setTimeout(refresh, 300);
}

// ---- Rendering ----

function render() {
  const tone = level();
  document.title = ({ bad: "Failing: ", wait: "Waiting: " }[tone] || "") + "hevy-garmin-sync";
  favicon(tone);
  const version = $("#version");
  version.textContent = `Version ${status.version}`;
  if (/^\d+\.\d+\.\d+$/.test(status.version)) version.href = `${REPO}/releases/tag/v${status.version}`;
  renderPreview();
  renderControl();
  renderServices();
  renderWorkouts();
  renderSettings();
}

// A preview's red banner (W-10). Plain text: both values are checked at startup, and textContent escapes anyway.
function renderPreview() {
  const banner = $("#preview");
  banner.hidden = !status.preview;
  if (status.preview) {
    const commit = status.preview.commit ? ` | Commit: ${status.preview.commit}` : "";
    banner.textContent = `You are viewing a preview release of hevy-garmin-sync | PR: ${status.preview.pr}${commit}`;
  }
}

function level() {
  const services = status.services.map((s) => s.state);
  if (services.includes("rejected") || status.workouts.some((w) => w.refused)) return "bad";
  if (services.includes("waiting") || status.sync.state === "waiting") return "wait";
  return "";
}

let icon = null; // the icon's SVG, fetched once for the tab's yellow or red dot
async function favicon(tone) {
  const badge = { wait: "#e0a020", bad: "#d6352b" }[tone];
  const link = $("#favicon");
  if (!badge) { link.href = "/icon.svg"; return; }
  icon = icon || await fetch("/icon.svg").then((r) => r.text());
  const dotted = icon.replace("</svg>", `<circle cx="25" cy="25" r="6.5" fill="${badge}" stroke="#fff" stroke-width="2"/></svg>`);
  link.href = "data:image/svg+xml," + encodeURIComponent(dotted);
}

function renderControl() {
  const run = status.sync;
  $("#last-run").innerHTML = status.last_daily_run ? `${esc(when(status.last_daily_run))}<small>${counts(status.last_counts)}</small>` : "Not yet";
  $("#next-run").textContent = when(status.next_daily_run);
  $("#started").textContent = when(status.started);
  $("#zone").textContent = status.time_zone;
  // No sync can run while Hevy's or Garmin's sign-in is rejected (W-3). A sync waiting to start still takes a Force (W-4).
  const blocked = status.services.some((s) => (s.name === "Hevy" || s.name === "Garmin") && s.state === "rejected");
  $("#sync").disabled = blocked || run.state !== "idle";
  $("#force").disabled = blocked || run.state === "running" || (run.state === "waiting" && run.force);
  const box = $("#notice");
  const garmin = status.services.find((s) => s.name === "Garmin");
  const rejected = status.services.filter((s) => s.state === "rejected").length;
  if (run.state === "running") {
    const step = run.step === "Writing workouts" && run.total ? `Writing workouts: ${run.done + 1} of ${run.total}` : run.step;
    const at = Math.max(STEPS.indexOf(run.step), 0);
    box.innerHTML = `<p class="msg tone-blue">${run.force ? "Force sync" : "Sync"}: ${esc(step)}</p>
      <div class="bar">${STEPS.map((_, i) => `<i class="${i < at ? "done" : i === at ? "now" : ""}"></i>`).join("")}</div>`;
    notice = null;
    return;
  }
  if (run.state === "waiting") {
    const why = /rate limiting/.test(garmin.reason) ? "Garmin asked the app to slow down." : "Garmin can't be reached right now.";
    box.innerHTML = msg(`${run.force ? "Force sync" : "Sync"} requested. ${why} Starts: ${esc(when(run.starts))}`, "wait");
    return;
  }
  if (notice && Date.now() < notice.until) { box.innerHTML = msg(notice.html, notice.tone); return; }
  if (rejected) {
    box.innerHTML = msg(`${rejected === 1 ? "A sign-in was" : `${rejected} sign-ins were`} rejected. The fix is under Services.`, "bad");
    return;
  }
  const recent = run.last_ended && Date.now() - new Date(run.last_ended) < 60000;
  if (recent) {
    const c = run.last_counts;
    box.innerHTML = msg(c ? `Synced at ${esc(when(run.last_ended))}: ${counts(c, " by Garmin")}.` : `The sync at ${esc(when(run.last_ended))} failed. The log says why.`, c && !c.failed ? "ok" : "bad");
    return;
  }
  box.innerHTML = msg(status.next_auto_sync ? `Next auto-sync: ${esc(when(status.next_auto_sync))}` : "Starting up", "ok");
}

function renderOffline() {
  document.title = "Reconnecting: hevy-garmin-sync";
  $("#sync").disabled = $("#force").disabled = true;
  $("#notice").innerHTML = msg("Can't reach the app. Reconnecting.", "wait");
}

function msg(html, tone) {
  return `<p class="msg tone-${tone}">${html}</p>`;
}

function renderServices() {
  $("#services").innerHTML = status.services.map((s) => {
    const [tone, label] = { working: ["ok", "Working"], waiting: ["wait", "Waiting"], rejected: ["bad", "Sign-in rejected"], off: ["off", "Off"] }[s.state];
    let why = "";
    if (s.state === "waiting") why = `${codeify(s.reason)}. Next try: ${esc(when(s.next_try))}`;
    if (s.state === "rejected") why = `${codeify(s.reason[0].toUpperCase() + s.reason.slice(1))}, and restart the app. ${EXTRA[s.name]}`;
    if (s.state === "off") why = codeify(s.reason);
    return `<div class="svc"><span class="name">${esc(s.name)}</span><span class="pill ${tone}">${label}</span>${why ? `<span class="why">${why}</span>` : ""}</div>`;
  }).join("");
}

function renderLog() {
  const last = logLines[logLines.length - 1];
  $("#latest").textContent = last ? `${clock(last.time)}  ${last.message.split("\n")[0]}` : "";
  const head = logMore
    ? '<button class="older" type="button" id="older">Load older lines</button>'
    : `<p class="start">Start of the log this app has kept since it started (up to 5,000 lines).</p>`;
  $("#lines").innerHTML = head + logLines.map((l) =>
    `<div class="l ${esc(l.level)}"><time>${esc(clock(l.time))}</time><span class="lv">${esc(l.level)}</span><span>${esc(l.message)}</span></div>`).join("");
}

function filters() {
  const workouts = status.workouts;
  const count = (test) => workouts.filter(test).length;
  const folders = [...new Set(workouts.map((w) => w.folder).filter(Boolean))].sort();
  const now = today();
  return [
    ["all", "All", workouts.length, () => true],
    ["today", "Today", count((w) => w.scheduled === now), (w) => w.scheduled === now],
    ["refused", "Refused", count((w) => w.refused), (w) => w.refused],
    ["sep"],
    ["trainer", "Hevy Trainer", count((w) => w.kind === "trainer"), (w) => w.kind === "trainer"],
    ["routine", "Routines", count((w) => w.kind === "routine"), (w) => w.kind === "routine"],
    ...folders.map((f) => ["f:" + f, f, count((w) => w.folder === f), (w) => w.folder === f, true]),
  ];
}

function renderWorkouts() {
  const all = filters();
  if (!all.some(([key, , n]) => key === filter && n)) filter = "all";
  $("#wcount").textContent = status.workouts.length || "";
  $("#chips").innerHTML = all.map(([key, label, n, , folder]) => key === "sep" ? '<span class="sep" aria-hidden="true"></span>'
    : n ? `<button class="chip${folder ? " folder" : ""}" type="button" data-filter="${esc(key)}" aria-pressed="${filter === key}">${esc(label)} ${n}</button>` : "").join("");

  if (!status.workouts.length) {
    $("#rows").innerHTML = status.last_daily_run
      ? '<p class="empty">No workouts yet. Make a routine in Hevy, or set <code>HEVY_SESSION</code> to sync Hevy Trainer, and it appears here at the next auto-sync.</p>'
      : '<p class="empty">Waiting for the first sync. Your workouts appear here once it reads Hevy.</p>';
    drawDetail(null, "");
    return;
  }
  const test = all.find(([key]) => key === filter)[3];
  const shown = status.workouts.filter((w) => test(w) && w.title.toLowerCase().includes(query.toLowerCase()));
  if (!selected || !status.workouts.some((w) => w.key === selected)) selected = status.workouts[0].key;
  $("#rows").innerHTML = shown.length ? shown.map((w) => {
    const [tone, label] = state(w);
    return `<button class="row" type="button" data-key="${esc(w.key)}" aria-current="${w.key === selected}">
      <span class="n">${esc(w.title)}</span><span class="pill ${tone}">${label}</span>
      <span class="m"><span>${esc(w.folder || (w.kind === "trainer" ? "Hevy Trainer" : "Routine"))}</span>${w.scheduled === today() ? '<span class="today">On today\'s calendar</span>' : ""}</span>
      <span class="when">Synced: ${w.synced ? esc(when(w.synced)) : "Never"}</span></button>`;
  }).join("") : '<p class="empty">No workout matches. Clear the search or pick All.</p>';
  renderDetail();
}

function state(workout) {
  if (!workout.syncing) return ["wait", "Not syncing"];
  if (workout.refused) return ["bad", "Refused"];
  return workout.garmin_id ? ["ok", "On Garmin"] : ["wait", "Not on Garmin yet"];
}

function link(label, href, why) {
  return href
    ? `<a class="lnk" href="${esc(href)}" target="_blank" rel="noopener">${label}${EXTERNAL}</a>`
    : `<a class="lnk" aria-disabled="true" role="link" title="${esc(why)}">${label}${EXTERNAL}</a>`;
}

// The line under a workout's links while Garmin has it: in sync only while Garmin and the workout's own
// source work. Otherwise the one that doesn't, and that this is the workout as it was last synced.
function syncLine(w) {
  const names = [w.kind === "trainer" ? "Hevy Trainer" : "Hevy", "Garmin"];
  const services = names.map((name) => status.services.find((s) => s.name === name)).filter(Boolean);
  const down = services.find((s) => s.state === "rejected") || services.find((s) => s.state === "waiting");
  if (!down) return "Garmin Connect is in sync with Hevy.";
  const what = down.state === "rejected" ? `${down.name}'s sign-in was rejected.` : `${down.name} is waiting${down.next_try ? ` until ${when(down.next_try)}` : ""}.`;
  return `${what} This is the workout as last synced${w.synced ? `, ${when(w.synced)}` : ""}.`;
}

// A workout its source doesn't list, kept in Garmin as it was (W-8): the app knows its name and its Garmin
// link, not its exercises. The source is down, or, with Hevy working, a folder or routine the settings name is gone.
function notSyncingLine(w) {
  const name = w.kind === "trainer" ? "Hevy Trainer" : "Hevy";
  const source = status.services.find((s) => s.name === name);
  const last = `Garmin has it as last synced${w.synced ? `, ${when(w.synced)}` : ""}.`;
  if (source && source.state === "rejected") return `${name}'s sign-in was rejected, so the app can't show this workout's exercises. ${last}`;
  if (source && source.state === "waiting") return `${name} is waiting${source.next_try ? ` until ${when(source.next_try)}` : ""}, so the app can't show this workout's exercises. ${last}`;
  // Hevy works, so a folder or routine the settings name is what's missing: renamed or deleted (F-14a).
  return `A folder in INCLUDE_HEVY_FOLDERS or a routine in INCLUDE_HEVY_ROUTINES is gone from Hevy, so the app leaves this workout as it was. ${last}`;
}

// Draws the detail pane only when it changed, so a poll keeps a selection, and an opened refusal stays open.
function drawDetail(key, html) {
  if (key === detail.key && html === detail.html) return;
  const open = key === detail.key && $("#detail details.slot[open]");
  $("#detail").innerHTML = html;
  if (open && $("#detail details.slot")) $("#detail details.slot").open = true;
  detail = { key, html };
}

function renderDetail() {
  const w = status.workouts.find((x) => x.key === selected);
  if (!w) { drawDetail(null, ""); return; }
  const [tone, label] = state(w);
  const rows = w.exercises.map((e) => {
    const report = e.chosen_by === "guess"
      ? `<a class="report" href="${esc(reportLink(e))}" target="_blank" rel="noopener">Report this match</a>` : "";
    // Trainer's direction shows beside "No weight" too: a rep range can move up with no weight to move (W-2).
    const direction = e.direction ? `<span class="dir ${e.direction === "up" ? "up" : e.direction === "down" ? "down" : ""}">${esc(e.direction)}</span>` : "";
    const weight = e.weight
      ? `${esc(e.weight)}${direction}${e.warmups ? `<span class="wu">Warm-ups ${esc(e.warmups)}</span>` : ""}`
      : `<span class="none">${esc(e.no_weight ? `No weight: ${e.no_weight}.` : "No weight")}</span>${direction}`;
    return `<tr><td>${esc(e.hevy)}</td>
      <td>${esc(e.garmin)}<span class="src ${e.chosen_by === "guess" ? "guess" : ""}">${CHOSEN[e.chosen_by] || ""}${report}</span></td>
      <td class="sets">${esc(e.sets || "")}${e.rest ? `<small>${esc(e.rest)}</small>` : ""}${e.last ? `<small class="prev">${esc(e.last)}</small>` : ""}</td>
      <td class="rx">${weight}</td></tr>`;
  }).join("");
  // No retry: the next daily run, which also comes before a retry that falls after it (status.py).
  const retry = esc(when(w.retry || status.next_daily_run));
  const slot = !w.syncing ? `<p class="slot quiet whole">${codeify(notSyncingLine(w))}</p>`
    : w.refused
    ? `<details class="slot bad"><summary><b>Refused by Garmin:</b> "${esc(w.refused)}" Next try: ${retry}, or press Sync now.</summary>
       <p>Garmin said: "${esc(w.refused)}" The app tries again on ${retry}. Sync now tries it at once.</p></details>`
    : w.garmin_id ? `<p class="slot quiet">${esc(syncLine(w))}</p>` : '<p class="slot quiet">Not on Garmin yet. It goes there at the next sync.</p>';
  drawDetail(w.key, `
    <button class="back" type="button" id="back">‹ All workouts</button>
    <div class="dhead">
      <div><h3>${esc(w.title)}</h3>
        <dl class="meta">
          <div><dt>Source</dt><dd>${w.kind === "trainer" ? "Hevy Trainer" : "Routine"}</dd></div>
          ${w.folder ? `<div><dt>Folder</dt><dd>${esc(w.folder)}</dd></div>` : ""}
          <div><dt>Scheduled</dt><dd>${w.scheduled ? esc(day(w.scheduled)) : "N/A"}</dd></div>
          <div><dt>Synced</dt><dd>${w.synced ? esc(when(w.synced)) : "Never"}</dd></div>
        </dl></div>
      <span class="pill ${tone}">${label}</span>
    </div>
    <div class="links">
      ${link("Hevy", w.hevy_id && `https://hevy.com/routine/${encodeURIComponent(w.hevy_id)}`, "Hevy Trainer workouts have no page on hevy.com")}
      ${link("Garmin Connect", w.garmin_id && `https://connect.garmin.com/app/workout/${encodeURIComponent(w.garmin_id)}?workoutType=strength_training`, "Garmin doesn't have this workout yet")}
    </div>
    ${slot}
    ${w.syncing ? `<div class="ex"><table>
      <thead><tr><th>Hevy exercise</th><th>Garmin exercise</th><th>Sets</th><th>Weight</th></tr></thead>
      <tbody>${rows}</tbody></table></div>` : ""}`);
}

function reportLink(exercise) {
  // The repo's exercise-match.yml form, its first two fields filled in by their ids (spec W-5).
  const params = new URLSearchParams({
    template: "exercise-match.yml",
    title: `Wrong Garmin exercise for ${exercise.hevy}`,
    "hevy-exercise": exercise.hevy,
    "garmin-exercise": exercise.garmin,
  });
  return `${REPO}/issues/new?${params}`;
}

function renderSettings() {
  $("#kv").innerHTML = Object.entries(status.settings).map(([key, value]) =>
    `<div><dt><code>${esc(key)}</code></dt><dd class="${value.startsWith("unset") ? "unset" : ""}">${esc(value)}</dd></div>`).join("");
}

// ---- Wiring ----

function setTheme(value) {
  if (value === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", value);
  document.querySelectorAll("[data-theme-set]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.themeSet === value)));
  store.set("theme", value);
}

function fromHash() {
  let wanted = "";
  try { wanted = decodeURIComponent(location.hash.slice(1)); } catch { /* not a hash this page wrote: show the first workout */ }
  if (wanted) { selected = wanted; if (status) renderWorkouts(); }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!target) return;
  if (target.id === "sync") sync(false);
  else if (target.id === "force") sync(true);
  else if (target.id === "older") olderLines();
  else if (target.id === "back") $("#split").classList.remove("showing");
  else if (target.dataset.filter) { filter = target.dataset.filter; renderWorkouts(); }
  else if (target.dataset.key) {
    selected = target.dataset.key;
    history.replaceState(null, "", "#" + selected);
    renderWorkouts();
    $("#split").classList.add("showing");
  } else if (target.dataset.themeSet) setTheme(target.dataset.themeSet);
});

$("#q").addEventListener("input", (event) => { query = event.target.value; renderWorkouts(); });
$("#only").addEventListener("change", (event) => { $("#lines").classList.toggle("only", event.target.checked); store.set("only", event.target.checked ? "1" : ""); });
$("#log").addEventListener("toggle", (event) => {
  store.set("log", event.target.open ? "1" : "");
  if (event.target.open) newLines().then(() => { $("#lines").scrollTop = $("#lines").scrollHeight; });
});
// Browsers offer navigator.clipboard only over HTTPS and on localhost, and the page is often served over plain
// HTTP on a home network. There a hidden textarea and execCommand("copy") still copy, inside the click.
function copyByHand(text) {
  const area = document.createElement("textarea");
  area.className = "clipboard";
  area.value = text;
  area.setAttribute("readonly", "");
  document.body.append(area);
  area.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch { /* copied stays false */ }
  area.remove();
  return copied;
}

let copyReset = null;
$("#copy").addEventListener("click", (event) => {
  const only = $("#only").checked;
  const text = logLines.filter((l) => !only || LOUD.has(l.level)).map((l) => `${clock(l.time, true)} ${l.level} ${l.message}`).join("\n");
  const button = event.currentTarget;
  const say = (label) => {
    button.textContent = label;
    clearTimeout(copyReset);
    copyReset = setTimeout(() => { button.textContent = "Copy log"; }, 1600);
  };
  const failed = () => {
    // Leave the lines selected, so the keyboard's copy still works.
    const range = document.createRange();
    range.selectNodeContents($("#lines"));
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    say("Couldn't copy");
  };
  const fallback = () => (copyByHand(text) ? say("Copied") : failed());
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => say("Copied"), fallback);
  else fallback();
  button.focus();
});
window.addEventListener("hashchange", fromHash);

setTheme(store.get("theme") || "system");
if (store.get("only")) { $("#only").checked = true; $("#lines").classList.add("only"); }
if (store.get("log")) $("#log").open = true;
fromHash();
refresh();
