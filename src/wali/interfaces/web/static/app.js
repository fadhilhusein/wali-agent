// Replies and supplier names are external input. Keep every dynamic value in textContent or a
// text node so it can never add markup to the page.
"use strict";

const $ = (id) => document.getElementById(id);
const roleSelect = $("role");
const log = $("log");
const messageBox = $("text");
const sendButton = $("send");
const resetButton = $("reset");
const mandateButton = $("mandate");

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

function updateConversationEmpty() {
  $("conversation-empty").hidden = log.children.length > 0;
}

function setChatBusy(busy, status = "") {
  log.setAttribute("aria-busy", String(busy));
  sendButton.disabled = busy;
  sendButton.textContent = busy ? "Sending..." : "Send message";
  $("chat-status").textContent = status;
}

function say(kind, text, label, tone = "") {
  const item = document.createElement("li");
  item.className = kind;
  if (tone) item.dataset.tone = tone;
  if (label) {
    const who = document.createElement("span");
    who.className = "who-said";
    who.textContent = label;
    item.append(who);
  }
  item.append(document.createTextNode(text));
  log.append(item);
  updateConversationEmpty();
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  item.scrollIntoView({ block: "end", behavior });
}

function money(amount, currency) {
  return `${Number(amount).toLocaleString("id-ID")} ${currency}`;
}

function addFact(list, name, value) {
  const term = document.createElement("dt");
  term.textContent = name;
  const detail = document.createElement("dd");
  detail.textContent = value;
  list.append(term, detail);
}

function describe(request) {
  const item = document.createElement("li");
  const title = document.createElement("strong");
  title.className = "request-title";
  title.textContent = `${request.kind === "payment" ? "Payment" : "Mandate"} from ${request.requested_by}`;
  item.append(title);

  const facts = document.createElement("dl");
  const summary = request.summary;
  if (summary) {
    addFact(facts, "Supplier", summary.supplier_name);
    addFact(facts, "Invoice", `${summary.invoice_number} (due ${summary.due_date})`);
    addFact(facts, "Amount", money(summary.amount, summary.currency));
    addFact(facts, "To account", `${summary.registered_account} (registered)`);
    addFact(facts, "Balance after", money(summary.balance_after, summary.currency));
  }
  for (const change of request.changes) addFact(facts, "Change", change);
  addFact(facts, "Expires", new Date(request.expires_at).toLocaleTimeString());
  item.append(facts);

  for (const warning of request.risk_warnings) {
    const box = document.createElement("p");
    box.className = "warning";
    box.textContent = `Warning: ${warning.message}`;
    item.append(box);
  }

  const status = document.createElement("p");
  status.className = "request-status";
  status.setAttribute("role", "status");
  item.append(status);

  const actions = document.createElement("div");
  actions.className = "actions";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.textContent = "Confirm";
  const decline = document.createElement("button");
  decline.type = "button";
  decline.className = "decline";
  decline.textContent = "Decline";

  const decide = (path, progress) => async () => {
    confirm.disabled = true;
    decline.disabled = true;
    status.textContent = progress;
    try {
      const result = await call(path, { role: role(), subject_id: request.subject_id });
      say("system", `Guard: ${result.message}`);
      await refresh();
    } catch (error) {
      status.textContent = error.message;
      confirm.disabled = false;
      decline.disabled = false;
    }
  };

  confirm.addEventListener("click", decide("/api/confirm", "Confirming this request..."));
  decline.addEventListener("click", decide("/api/cancel", "Declining this request..."));
  actions.append(confirm, decline);
  item.append(actions);
  return item;
}

function setQueueState(state, message = "") {
  const list = $("requests");
  const loading = $("requests-loading");
  const empty = $("empty");
  const error = $("requests-error");
  loading.hidden = state !== "loading";
  empty.hidden = state !== "empty";
  error.hidden = state !== "error";
  list.hidden = state !== "ready";
  list.setAttribute("aria-busy", String(state === "loading"));
  if (state === "error") $("requests-error-message").textContent = message;
}

async function refresh() {
  const list = $("requests");
  setQueueState("loading");
  try {
    const { requests } = await call(`/api/pending?role=${encodeURIComponent(role())}`);
    list.replaceChildren(...requests.map(describe));
    $("request-count").textContent = String(requests.length);
    setQueueState(requests.length ? "ready" : "empty");
  } catch (error) {
    list.replaceChildren();
    $("request-count").textContent = "!";
    setQueueState("error", error.message);
  }
  mandateButton.closest(".mandate-action").hidden = role() !== "owner";
}

async function send(event) {
  event.preventDefault();
  const text = messageBox.value.trim();
  if (!text || sendButton.disabled) return;
  messageBox.value = "";
  say("me", text, role());
  setChatBusy(true, "Wali is reviewing your request...");
  try {
    const result = await call("/api/chat", { role: role(), text });
    say("wali", result.reply, "Wali");
    if (result.blocked) {
      say("system", "The outgoing safety check blocked this answer.", "", "warning");
    }
    for (const request of result.new_requests) {
      if (request.required_role !== role()) {
        say(
          "system",
          `Sent to the ${request.required_role} for confirmation. Nothing has happened yet.`
        );
      }
    }
  } catch (error) {
    say("system", error.message, "", "error");
  } finally {
    setChatBusy(false);
    messageBox.focus();
    await refresh();
  }
}

function bindEvents() {
  roleSelect.addEventListener("change", () => {
    say("system", `You are now acting as ${role()}.`);
    refresh();
  });

  $("ask").addEventListener("submit", send);
  messageBox.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) send(event);
  });

  for (const prompt of document.querySelectorAll(".quick-prompt")) {
    prompt.addEventListener("click", () => {
      messageBox.value = prompt.dataset.prompt;
      messageBox.focus();
      $("chat-status").textContent = "Prompt added. Review it, then send when ready.";
    });
  }

  resetButton.addEventListener("click", async () => {
    resetButton.disabled = true;
    resetButton.textContent = "Resetting...";
    try {
      await call("/api/reset", { role: role() });
      log.replaceChildren();
      updateConversationEmpty();
      $("chat-status").textContent = "Fresh conversation ready.";
      messageBox.focus();
    } catch (error) {
      say("system", error.message, "", "error");
    } finally {
      resetButton.disabled = false;
      resetButton.textContent = "New conversation";
    }
  });

  mandateButton.addEventListener("click", async () => {
    mandateButton.disabled = true;
    mandateButton.textContent = "Drafting mandate...";
    try {
      const result = await call("/api/mandate", { role: role() });
      say("system", `Guard: ${result.message}`);
    } catch (error) {
      say("system", error.message, "", "error");
    } finally {
      mandateButton.disabled = false;
      mandateButton.textContent = "Draft demo mandate";
      await refresh();
    }
  });

  $("retry-requests").addEventListener("click", refresh);
}

async function start() {
  bindEvents();
  updateConversationEmpty();
  setQueueState("loading");
  try {
    const info = await call("/api/info");
    $("simulation").textContent = info.simulation;
    for (const name of info.roles) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      roleSelect.append(option);
    }
    if (!info.screening_model) {
      say("system", "Outside text is screened with built-in rules only.");
    }
    await refresh();
  } catch (error) {
    say("system", `Wali could not start: ${error.message}`, "", "error");
    $("request-count").textContent = "!";
    setQueueState("error", error.message);
    sendButton.disabled = true;
    resetButton.disabled = true;
    mandateButton.disabled = true;
    roleSelect.disabled = true;
  }
}

start();
