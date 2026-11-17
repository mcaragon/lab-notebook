/* Admin dashboard: accounts (create, edit, disable, password, sign out, reset or export a notebook, delete), invite
   links, demo limits, recent sign-ins and changes, and backups. Only admins reach it (the server checks too). */
import { $, $$, api, esc, toast } from "./util.js";
import { state } from "./state.js";

let data = null;
let editing = null;
let lastInvite = null;

const when = (v) => (v ? new Date(v).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–");
const day = (v) => (v ? new Date(v).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "–");
const size = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} kB`);
const expired = (u) => u.expires_at && Date.parse(u.expires_at) <= Date.now();

export async function renderAdmin(app) {
  document.title = "Admin · Lab Notebook";
  if (!state.user?.is_admin) { app.innerHTML = '<div class="panel">Admins only. <a href="#/">Back</a></div>'; return; }
  try { data = await api("GET", "/api/admin/overview"); }
  catch (e) { app.innerHTML = `<div class="panel">Could not load: ${esc(e.message)}</div>`; return; }
  draw(app);
}

async function reload(app) {
  data = await api("GET", "/api/admin/overview");
  draw(app);
}

async function act(app, method, path, body, msg) {
  try {
    const d = await api(method, path, body);
    if (msg) toast(msg);
    await reload(app);
    return d;
  } catch (e) { toast(e.message, true); return null; }
}

function userRow(u) {
  const status = !u.active ? '<span class="tag t-bad">disabled</span>' : expired(u) ? '<span class="tag t-bad">expired</span>' : "";
  const self = u.id === data.me;
  return `<tr data-uid="${u.id}" class="${!u.active || expired(u) ? "muted-row" : ""}">
    <td><b>${esc(u.display_name || u.username)}</b><div class="sub">${esc(u.username)}${self ? " · you" : ""}</div></td>
    <td>${u.is_admin ? '<span class="tag role-admin">admin</span>' : ""}${u.demo ? '<span class="tag t-warn">demo</span>' : ""}${status}</td>
    <td class="num">${u.n_experiments}<span class="sub"> exp</span> · ${u.n_projects}<span class="sub"> proj</span></td>
    <td>${when(u.last_login_at)}<div class="sub">${u.n_sessions ? `${u.n_sessions} active session${u.n_sessions === 1 ? "" : "s"}` : "signed out"}</div></td>
    <td>${when(u.last_change)}</td>
    <td>${u.expires_at ? day(u.expires_at) : "never"}</td>
    <td class="num">${u.max_experiments ?? "–"}</td>
    <td class="actions">
      <button class="btn small" data-edit="${u.id}">Edit</button>
      <details class="menu"><summary class="btn small" aria-label="More actions">⋯</summary><div class="menu-list">
        <button data-pw="${u.id}">Set password…</button>
        <button data-signout="${u.id}">Sign out everywhere</button>
        <a href="/api/admin/users/${u.id}/export.json">Export notebook (JSON)</a>
        <button data-reset="${u.id}">Reset notebook (delete all experiments)…</button>
        <button data-active="${u.id}" data-to="${u.active ? 0 : 1}">${u.active ? "Disable" : "Enable"} account</button>
        ${self ? "" : `<button class="danger" data-delete="${u.id}">Delete account…</button>`}
      </div></details></td>
  </tr>${editing === u.id ? `<tr class="edit-row"><td colspan="8">${editForm(u)}</td></tr>` : ""}`;
}

function editForm(u) {
  return `<form class="admin-form" id="edit-form" data-uid="${u.id}">
    <label class="field"><span>Name</span><input name="display_name" value="${esc(u.display_name || "")}"></label>
    <label class="field"><span>Role</span><select name="role"><option value="user" ${u.is_admin ? "" : "selected"}>User</option>
      <option value="admin" ${u.is_admin ? "selected" : ""}>Admin</option></select></label>
    <label class="field"><span>Account expires</span><input type="date" name="expires_at" value="${u.expires_at ? u.expires_at.slice(0, 10) : ""}"></label>
    <label class="field"><span>Experiment limit</span><input type="number" min="0" name="max_experiments" value="${u.max_experiments ?? ""}" placeholder="none"></label>
    <label class="inline"><input type="checkbox" name="demo" ${u.demo ? "checked" : ""}> Demo account</label>
    <label class="inline"><input type="checkbox" name="active" ${u.active ? "checked" : ""}> Active</label>
    <div class="row"><button class="btn primary small">Save</button><button type="button" class="btn small" id="edit-cancel">Cancel</button></div>
  </form>`;
}

function draw(app) {
  const users = data.users;
  const host = location.origin;
  app.innerHTML = `<div class="home admin">
    <div class="page-head"><div><h1>Admin</h1><p class="hint">Accounts, invites, demo limits, activity and backups. Every account has its own private notebook.</p></div>
      <span class="spacer"></span><a class="btn" href="/api/admin/backup.sqlite">⬇ Back up the database</a></div>
    <div class="stat-row">
      <div class="stat"><span class="k-l">Accounts</span><b>${users.length}</b></div>
      <div class="stat"><span class="k-l">Experiments</span><b>${data.db.counts.experiments}</b></div>
      <div class="stat"><span class="k-l">Projects</span><b>${data.db.counts.projects}</b></div>
      <div class="stat"><span class="k-l">Database</span><b>${size(data.db.size_bytes)}</b></div>
    </div>
    <div class="panel"><div class="row sec-head"><h2>Accounts</h2></div>
      <div class="table-wrap"><table class="admin-table">
        <thead><tr><th>User</th><th></th><th class="num">Notebook</th><th>Last sign-in</th><th>Last change</th><th>Expires</th><th class="num">Limit</th><th></th></tr></thead>
        <tbody>${users.map(userRow).join("")}</tbody></table></div>
      <details class="add-user"><summary class="btn small">＋ Create an account</summary>
        <form class="admin-form" id="new-user">
          <label class="field"><span>User name</span><input name="username" required autocapitalize="off" autocomplete="off"></label>
          <label class="field"><span>Name</span><input name="display_name"></label>
          <label class="field"><span>Password (10+ characters; tell them to change it)</span><input name="password" type="text" autocomplete="off" required></label>
          <label class="field"><span>Role</span><select name="role"><option value="user">User</option><option value="admin">Admin</option></select></label>
          <label class="field"><span>Account expires</span><input type="date" name="expires_at"></label>
          <label class="field"><span>Experiment limit</span><input type="number" min="0" name="max_experiments" placeholder="none"></label>
          <label class="inline"><input type="checkbox" name="demo" checked> Demo account</label>
          <div class="row"><button class="btn primary small">Create</button></div>
        </form></details>
    </div>
    <div class="panel"><div class="row sec-head"><h2>Invite links</h2><span class="spacer"></span>
      <span class="hint">A link lets one person create their own account. Each link works once.</span></div>
      ${lastInvite ? `<div class="invite-new"><b>New invite link</b> (shown once; copy it now)
        <div class="row"><input class="grow mono" id="invite-url" readonly value="${esc(host + lastInvite.path)}">
        <button class="btn small primary" id="invite-copy">Copy</button></div></div>` : ""}
      <form class="admin-form" id="new-invite">
        <label class="field"><span>For (note)</span><input name="note" placeholder="e.g. Sam"></label>
        <label class="field"><span>Link valid for (days)</span><input type="number" name="valid_days" min="1" max="90" value="7"></label>
        <label class="field"><span>Account lasts (days)</span><input type="number" name="account_days" min="0" value="30" placeholder="forever"></label>
        <label class="field"><span>Experiment limit</span><input type="number" name="max_experiments" min="0" value="10" placeholder="none"></label>
        <label class="field"><span>Role</span><select name="role"><option value="user">User</option><option value="admin">Admin</option></select></label>
        <label class="inline"><input type="checkbox" name="demo" checked> Demo account</label>
        <div class="row"><button class="btn primary small">Create invite link</button></div>
      </form>
      ${data.invites.length ? `<table class="admin-table compact"><thead><tr><th>For</th><th>Status</th><th>Created</th><th>Link expires</th><th>Terms</th><th></th></tr></thead>
        <tbody>${data.invites.map((i) => `<tr><td>${esc(i.note || "–")}</td>
          <td><span class="tag ${i.status === "open" ? "t-ok" : ""}">${esc(i.status)}</span>${i.used_by ? ` <span class="sub">by ${esc(i.used_by)}</span>` : ""}</td>
          <td>${day(i.created_at)}</td><td>${day(i.expires_at)}</td>
          <td class="sub">${[i.demo ? "demo" : "", i.role === "admin" ? "admin" : "", i.account_days ? `${i.account_days} days` : "", i.max_experiments ? `≤ ${i.max_experiments} exp` : ""].filter(Boolean).join(" · ")}</td>
          <td class="actions">${i.status === "open" ? `<button class="btn small danger" data-revoke="${i.id}">Revoke</button>` : ""}</td></tr>`).join("")}</tbody></table>` : ""}
    </div>
    <div class="admin-cols">
      <div class="panel"><div class="row sec-head"><h2>Recent sign-ins</h2></div>
        <table class="admin-table compact"><thead><tr><th>When</th><th>User</th><th>Address</th><th>Result</th></tr></thead>
        <tbody>${data.attempts.map((a) => `<tr><td>${when(a.ts)}</td><td>${esc(a.username || "")}</td><td class="mono sub">${esc(a.ip || "")}</td>
          <td>${a.ok ? '<span class="tag t-ok">ok</span>' : '<span class="tag t-bad">failed</span>'} <span class="sub">${esc(a.reason || "")}</span></td></tr>`).join("")
          || '<tr><td colspan="4" class="empty">None yet.</td></tr>'}</tbody></table></div>
      <div class="panel"><div class="row sec-head"><h2>Recent changes</h2></div>
        <table class="admin-table compact"><thead><tr><th>When</th><th>User</th><th>Experiment</th></tr></thead>
        <tbody>${data.changes.map((c) => `<tr><td>${when(c.updated_at)}</td><td>${esc(c.username || "")}</td><td>${esc(c.title)}</td></tr>`).join("")
          || '<tr><td colspan="3" class="empty">None yet.</td></tr>'}</tbody></table></div>
    </div></div>`;
  bind(app);
}

const formData = (form) => {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.type === "number") out[el.name] = el.value === "" ? 0 : Number(el.value);
    else out[el.name] = el.value.trim();
  }
  return out;
};

function bind(app) {
  $$("[data-edit]", app).forEach((b) => (b.onclick = () => { editing = Number(b.dataset.edit); draw(app); }));
  const ef = $("#edit-form", app);
  if (ef) {
    $("#edit-cancel", ef).onclick = () => { editing = null; draw(app); };
    ef.onsubmit = async (e) => {
      e.preventDefault();
      const d = await act(app, "PUT", `/api/admin/users/${ef.dataset.uid}`, formData(ef), "Saved.");
      if (d) { editing = null; draw(app); }
    };
  }
  $$("[data-pw]", app).forEach((b) => (b.onclick = () => {
    const pw = prompt("New password for this account (at least 10 characters). They are signed out everywhere:");
    if (pw) act(app, "POST", `/api/admin/users/${b.dataset.pw}/password`, { password: pw }, "Password set.");
  }));
  $$("[data-signout]", app).forEach((b) => (b.onclick = () => act(app, "POST", `/api/admin/users/${b.dataset.signout}/signout`, undefined, "Signed out.")));
  $$("[data-active]", app).forEach((b) => (b.onclick = () => act(app, "PUT", `/api/admin/users/${b.dataset.active}`, { active: b.dataset.to === "1" })));
  $$("[data-reset]", app).forEach((b) => (b.onclick = () => {
    const u = data.users.find((x) => x.id === Number(b.dataset.reset));
    if (confirm(`Delete all ${u.n_experiments} experiments and ${u.n_projects} projects of ${u.username}? The account stays.`))
      act(app, "POST", `/api/admin/users/${u.id}/reset`, undefined, "Notebook reset.");
  }));
  $$("[data-delete]", app).forEach((b) => (b.onclick = () => {
    const u = data.users.find((x) => x.id === Number(b.dataset.delete));
    if (prompt(`Delete ${u.username} and their whole notebook? This cannot be undone. Type the user name to confirm:`) === u.username)
      act(app, "DELETE", `/api/admin/users/${u.id}`, undefined, "Account deleted.");
  }));
  $("#new-user", app).onsubmit = async (e) => {
    e.preventDefault();
    const d = await act(app, "POST", "/api/admin/users", formData(e.target), "Account created.");
    if (d) e.target.reset();
  };
  $("#new-invite", app).onsubmit = async (e) => {
    e.preventDefault();
    const d = await act(app, "POST", "/api/admin/invites", formData(e.target));
    if (d) { lastInvite = d; draw(app); $("#invite-url")?.select(); }
  };
  const copy = $("#invite-copy", app);
  if (copy) copy.onclick = async () => {
    const inp = $("#invite-url", app);
    try { await navigator.clipboard.writeText(inp.value); toast("Copied."); }
    catch { inp.select(); document.execCommand("copy"); toast("Copied."); }
  };
  $$("[data-revoke]", app).forEach((b) => (b.onclick = () => act(app, "DELETE", `/api/admin/invites/${b.dataset.revoke}`, undefined, "Invite revoked.")));
  // close other "⋯" menus when one opens
  $$("details.menu", app).forEach((d) => d.addEventListener("toggle", () => {
    if (d.open) $$("details.menu", app).forEach((o) => { if (o !== d) o.open = false; });
  }));
}
