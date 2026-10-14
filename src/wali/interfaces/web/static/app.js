// The demo page. Everything shown is set with textContent, never as HTML, because replies and
// supplier names come from outside and must not be able to add markup to the page.
"use strict";

const $ = (id) => document.getElementById(id);
const roleSelect = $("role");
const log = $("log");

function role() {
  return roleSelect.value;
}

async function call(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "The request failed.");
  }
  return data;
}

function say(kind, text, label) {
  const item = document.createElement("li");
  item.className = kind;
  if (label) {
    const who = document.createElement("span");
    who.className = "who-said";
    who.textContent = label;
    item.append(who);
  }
  item.append(document.createTextNode(text));
  log.append(item);
  item.scrollIntoView({ block: "end" });
}

function money(amount, currency) {
  return `${Number(amount).toLocaleString("id-ID")} ${currency}`;
}

function describe(request) {
  const item = document.createElement("li");
  const title = document.createElement("strong");
  title.textContent = `${request.kind === "payment" ? "Payment" : "Mandate"} from ${request.requested_by}`;
  item.append(title);

  const facts = document.createElement("dl");
  const add = (name, value) => {
    const dt = document.createElement("dt");
    dt.textContent = name;
    const dd = document.createElement("dd");
    dd.textContent = value;
    facts.append(dt, dd);
  };
  const s = request.summary;
  if (s) {
    add("Supplier", s.supplier_name);
    add("Invoice", `${s.invoice_number} (due ${s.due_date})`);
    add("Amount", money(s.amount, s.currency));
    add("To account", `${s.registered_account} (registered)`);
    add("Balance after", money(s.balance_after, s.currency));
  }
  for (const change of request.changes) add("Change", change);
  add("Expires", new Date(request.expires_at).toLocaleTimeString());
  item.append(facts);

  for (const warning of request.risk_warnings) {
    const box = document.createElement("p");
    box.className = "warning";
    box.textContent = `Warning: ${warning.message}`;
    item.append(box);
  }

  const actions = document.createElement("div");
  actions.className = "actions";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.textContent = "Confirm";
  const decline = document.createElement("button");
  decline.type = "button";
  decline.className = "decline";
  decline.textContent = "Decline";
  const decide = (path) => async () => {
    confirm.disabled = decline.disabled = true;
    try {
      const result = await call(path, { role: role(), subject_id: request.subject_id });
      say("system", `Guard: ${result.message}`);
    } catch (error) {
      say("system", error.message);
    }
    refresh();
  };
  confirm.addEventListener("click", decide("/api/confirm"));
  decline.addEventListener("click", decide("/api/cancel"));
  actions.append(confirm, decline);
  item.append(actions);
  return item;
}

async function refresh() {
  const list = $("requests");
  try {
    const { requests } = await call(`/api/pending?role=${encodeURIComponent(role())}`);
    list.replaceChildren(...requests.map(describe));
    $("empty").hidden = requests.length > 0;
  } catch (error) {
    say("system", error.message);
  }
  $("mandate").hidden = role() !== "owner";
}

async function send(event) {
  event.preventDefault();
  const box = $("text");
  const text = box.value.trim();
  if (!text) return;
  box.value = "";
  say("me", text, role());
  $("send").disabled = true;
  try {
    const result = await call("/api/chat", { role: role(), text });
    say("wali", result.reply, "Wali");
    if (result.blocked) say("system", "This answer was blocked by the outgoing check.");
    for (const request of result.new_requests) {
      if (request.required_role !== role()) {
        say("system", `Sent to the ${request.required_role} for confirmation. Nothing has happened yet.`);
      }
    }
  } catch (error) {
    say("system", error.message);
  }
  $("send").disabled = false;
  box.focus();
  refresh();
}

async function start() {
  const info = await call("/api/info");
  $("simulation").textContent = info.simulation;
  for (const name of info.roles) {
    const option = document.createElement("option");
    option.value = option.textContent = name;
    roleSelect.append(option);
  }
  if (!info.screening_model) {
    say("system", "Screening of outside text runs on built-in rules only.");
  }
  roleSelect.addEventListener("change", () => {
    say("system", `You are now acting as ${role()}.`);
    refresh();
  });
  $("ask").addEventListener("submit", send);
  $("text").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) send(event);
  });
  $("reset").addEventListener("click", async () => {
    await call("/api/reset", { role: role() });
    log.replaceChildren();
    say("system", "Started a fresh conversation.");
  });
  $("mandate").addEventListener("click", async () => {
    try {
      const result = await call("/api/mandate", { role: role() });
      say("system", `Guard: ${result.message}`);
    } catch (error) {
      say("system", error.message);
    }
    refresh();
  });
  refresh();
}

start();
