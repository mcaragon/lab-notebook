/* Sign-in pages: sign in, first start (create the admin account with the setup code from the server log), and
   sign up with an invite link. Shown full-window, without the sidebar. */
import { $, api, esc } from "./util.js";

function shell(title, sub, form, foot = "") {
  document.body.classList.add("auth-view");
  document.title = `${title} · Lab Notebook`;
  $("#app").innerHTML = `<div class="auth-wrap"><form class="auth-card" id="auth-form" autocomplete="on" novalidate>
    <div class="auth-brand"><img src="/static/icon.svg" alt="" width="34" height="34"><span>Lab Notebook</span></div>
    <h1>${esc(title)}</h1>${sub ? `<p class="hint">${sub}</p>` : ""}
    ${form}
    <div class="auth-err" id="auth-err" role="alert"></div>
    <button class="btn primary auth-go" id="auth-go">${esc(title)}</button>
    ${foot}</form></div>`;
}

function field(id, label, type = "text", extra = "") {
  return `<label class="field"><span>${label}</span><input id="${id}" type="${type}" ${extra}></label>`;
}

function bind(submit) {
  const form = $("#auth-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#auth-go");
    btn.disabled = true;
    $("#auth-err").textContent = "";
    try { await submit(); }
    catch (err) { $("#auth-err").textContent = err.message; btn.disabled = false; }
  };
  form.querySelector("input")?.focus();
}

const val = (id) => $("#" + id).value;
const done = () => { document.body.classList.remove("auth-view"); location.replace(location.pathname + "#/"); location.reload(); };

export function renderLogin(message = "") {
  shell("Sign in", message ? esc(message) : "",
    field("a-user", "User name", "text", 'autocomplete="username" autocapitalize="off" spellcheck="false"')
    + field("a-pass", "Password", "password", 'autocomplete="current-password"'),
    `<p class="hint auth-foot">No account? Ask the person who runs this notebook for an invite link.</p>`);
  bind(async () => {
    await api("POST", "/api/auth/login", { username: val("a-user").trim(), password: val("a-pass") });
    done();
  });
}

export function renderSetup() {
  shell("Create the admin account",
    "First start: there are no accounts yet. The <b>setup code</b> is printed in the server log " +
    "(on Unraid: the container's log; or <code>docker logs lab-notebook</code>). The admin account gets the existing notebook.",
    field("a-code", "Setup code", "text", 'autocomplete="one-time-code" autocapitalize="characters" placeholder="XXXXXX-XXXXXX-XXXXXX"')
    + field("a-user", "User name", "text", 'autocomplete="username" autocapitalize="off"')
    + field("a-name", "Your name (for reports)", "text", 'autocomplete="name"')
    + field("a-pass", "Password (at least 10 characters)", "password", 'autocomplete="new-password"')
    + field("a-pass2", "Repeat the password", "password", 'autocomplete="new-password"'));
  bind(async () => {
    if (val("a-pass") !== val("a-pass2")) throw new Error("The passwords do not match.");
    await api("POST", "/api/auth/setup", { code: val("a-code"), username: val("a-user").trim(), password: val("a-pass"),
      display_name: val("a-name").trim() || null });
    done();
  });
}

export async function renderInvite(token) {
  let info;
  try { info = await api("GET", `/api/auth/invite/${encodeURIComponent(token)}`); }
  catch (e) {
    shell("Invite link", esc(e.message), "", '<p class="hint auth-foot"><a href="#/">Sign in instead</a></p>');
    $("#auth-go").remove();
    return;
  }
  const terms = [info.demo ? "a demo account" : "an account",
    info.account_days ? `for ${info.account_days} days` : "", info.max_experiments ? `with up to ${info.max_experiments} experiments` : ""]
    .filter(Boolean).join(" ");
  shell("Create your account", `You have been invited to ${esc(terms)}. Your notebook is private to you.`,
    field("a-user", "User name", "text", 'autocomplete="username" autocapitalize="off" spellcheck="false"')
    + field("a-name", "Your name (for reports)", "text", 'autocomplete="name"')
    + field("a-pass", "Password (at least 10 characters)", "password", 'autocomplete="new-password"')
    + field("a-pass2", "Repeat the password", "password", 'autocomplete="new-password"'));
  bind(async () => {
    if (val("a-pass") !== val("a-pass2")) throw new Error("The passwords do not match.");
    await api("POST", `/api/auth/invite/${encodeURIComponent(token)}`,
      { username: val("a-user").trim(), password: val("a-pass"), display_name: val("a-name").trim() || null });
    done();
  });
}

export async function changePassword() {
  const current = prompt("Current password:");
  if (current === null) return;
  const next = prompt("New password (at least 10 characters):");
  if (next === null) return;
  if (prompt("Repeat the new password:") !== next) throw new Error("The passwords do not match.");
  await api("POST", "/api/auth/password", { current, new: next });
}

export async function signOut() {
  try { await api("POST", "/api/auth/logout"); } catch { /* signed out anyway */ }
  location.replace(location.pathname + "#/");
  location.reload();
}
