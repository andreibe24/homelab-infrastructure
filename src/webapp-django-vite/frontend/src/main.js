import "./style.css";

const authPanel = document.querySelector("#auth-panel");
const chatPanel = document.querySelector("#chat-panel");
const authForm = document.querySelector("#auth-form");
const messageForm = document.querySelector("#message-form");
const messagesList = document.querySelector("#messages");
const status = document.querySelector("#status");
const usernameLabel = document.querySelector("#current-user");
const tabs = [...document.querySelectorAll('[role="tab"]')];
const toolList = document.querySelector("#tool-list");
const toolResult = document.querySelector("#tool-result");
const useDraftButton = document.querySelector("#use-draft-button");
let csrfToken = "";
let session = 0;
let loadingMessages = false;
let toolsBusy = false;
let lastMessages = "";
let draft = "";

function showStatus(message) {
  status.textContent = message;
}

function selectTab(selected) {
  for (const tab of tabs) {
    const active = tab === selected;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
  }
}

for (const tab of tabs) {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next = event.key === "Home" ? tabs[0]
        : event.key === "End" ? tabs.at(-1)
          : tabs[(tabs.indexOf(tab) + 1) % tabs.length];
      selectTab(next);
      next.focus();
    }
  });
}

function setAnonymous() {
  session += 1;
  chatPanel.hidden = true;
  authPanel.hidden = false;
  messagesList.replaceChildren();
  toolList.replaceChildren();
  toolResult.hidden = true;
  document.querySelector("#forum-summary").hidden = true;
  document.querySelector("#summary-text").textContent = "";
  document.querySelector("#tool-output").textContent = "";
  document.querySelector("#reply-idea").value = "";
  messageForm.reset();
  usernameLabel.textContent = "";
  lastMessages = "";
  draft = "";
  selectTab(tabs[0]);
}

async function request(path, options = {}) {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (method !== "GET") headers.set("X-CSRFToken", csrfToken);

  const response = await fetch(path, {
    ...options, method, headers, credentials: "same-origin",
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await response.json() : {};
  if (!response.ok) {
    if (response.status === 401 && !chatPanel.hidden) setAnonymous();
    throw new Error(data.error ?? `Request failed (${response.status}). Please retry.`);
  }
  if (!isJson) throw new Error("The server returned an unexpected response.");
  return data;
}

async function refreshCsrfToken() {
  const data = await request("/api/csrf/");
  csrfToken = data.csrfToken;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value));
}

function renderMessages(messages) {
  const serialized = JSON.stringify(messages);
  if (serialized === lastMessages) return;
  const atBottom = !lastMessages
    || messagesList.scrollHeight - messagesList.scrollTop - messagesList.clientHeight < 60;
  lastMessages = serialized;
  messagesList.replaceChildren();
  if (messages.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "It’s quiet around the fire. Start the conversation.";
    messagesList.append(empty);
    return;
  }
  for (const message of messages) {
    const item = document.createElement("li");
    item.className = "message";
    const heading = document.createElement("div");
    heading.className = "message-heading";
    const author = document.createElement("strong");
    author.textContent = message.username;
    const time = document.createElement("time");
    time.dateTime = message.createdAt;
    time.textContent = formatDate(message.createdAt);
    heading.append(author, time);
    const content = document.createElement("p");
    content.textContent = message.content;
    item.append(heading, content);
    messagesList.append(item);
  }
  if (atBottom) messagesList.scrollTop = messagesList.scrollHeight;
}

async function loadMessages() {
  if (loadingMessages) return;
  const currentSession = session;
  loadingMessages = true;
  try {
    const data = await request("/api/messages/");
    if (currentSession === session) renderMessages(data.messages);
  } finally {
    loadingMessages = false;
  }
}

function setToolBusy(busy) {
  toolsBusy = busy;
  document.querySelector("#tools-view").setAttribute("aria-busy", String(busy));
  for (const button of document.querySelectorAll("[data-tool], #summarize-button")) {
    button.disabled = busy;
  }
}

async function executeTool(name, title, inForum = false) {
  if (toolsBusy) return;
  const currentSession = session;
  const idea = document.querySelector("#reply-idea").value.trim();
  if (name === "draft_reply" && !idea) {
    showStatus("Enter a reply idea first.");
    document.querySelector("#reply-idea").focus();
    return;
  }
  setToolBusy(true);
  if (!inForum) {
    toolResult.hidden = true;
    useDraftButton.hidden = true;
    draft = "";
  }
  showStatus(`Running ${title.toLowerCase()}…`);
  try {
    const data = await request(`/api/tools/${name}/`, {
      method: "POST",
      body: JSON.stringify(name === "draft_reply" ? { idea } : {}),
    });
    if (currentSession !== session) return;
    if (inForum) {
      document.querySelector("#summary-text").textContent = data.text;
      document.querySelector("#forum-summary").hidden = false;
    } else {
      document.querySelector("#result-title").textContent = title;
      toolResult.querySelector(".muted").textContent = name === "recent_messages"
        ? "Latest forum messages, read directly from the database."
        : "AI-generated text may be inaccurate. Review before sharing.";
      document.querySelector("#tool-output").textContent = data.text
        ?? (data.messages.map((message) => `${message.username}: ${message.content}`).join("\n\n")
          || "No messages yet. Start a conversation in the Forum tab.");
      draft = name === "draft_reply" ? data.text : "";
      useDraftButton.hidden = !draft || draft.length > 2000;
      toolResult.hidden = false;
    }
    showStatus("Done. Nothing has been posted.");
  } catch (error) {
    if (currentSession === session) showStatus(error.message);
  } finally {
    setToolBusy(false);
  }
}

async function loadTools() {
  const currentSession = session;
  const data = await request("/api/tools/");
  if (currentSession !== session) return;
  toolList.replaceChildren();
  for (const tool of data.tools) {
    const card = document.createElement("div");
    card.className = "tool-card";
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.tool = tool.name;
    button.textContent = tool.title;
    button.disabled = toolsBusy;
    button.addEventListener("click", () => executeTool(tool.name, tool.title));
    const description = document.createElement("p");
    description.className = "muted";
    description.textContent = tool.description;
    const label = document.createElement("code");
    label.textContent = `${tool.name} · ${tool.usesAI ? "AI" : "database"}`;
    card.append(button, description, label);
    toolList.append(card);
  }
}

function setAuthenticated(username) {
  session += 1;
  usernameLabel.textContent = `@${username}`;
  authPanel.hidden = true;
  chatPanel.hidden = false;
  showStatus("");
  loadMessages().catch((error) => showStatus(error.message));
  loadTools().catch((error) => showStatus(error.message));
}

function disableForm(form, disabled) {
  for (const button of form.querySelectorAll("button")) button.disabled = disabled;
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(authForm);
  const mode = event.submitter?.value ?? "login";
  disableForm(authForm, true);
  showStatus("Signing you in…");
  try {
    const data = await request(`/api/${mode}/`, {
      method: "POST",
      body: JSON.stringify({
        username: formData.get("username"), password: formData.get("password"),
      }),
    });
    authForm.reset();
    await refreshCsrfToken();
    setAuthenticated(data.username);
  } catch (error) {
    showStatus(error.message);
  } finally {
    disableForm(authForm, false);
  }
});

messageForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = messageForm.elements.content;
  const original = input.value;
  const content = original.trim();
  if (!content) return;
  const currentSession = session;
  disableForm(messageForm, true);
  try {
    await request("/api/messages/post/", {
      method: "POST", body: JSON.stringify({ content }),
    });
    if (currentSession !== session) return;
    if (input.value === original) input.value = "";
    showStatus("Message posted.");
    await loadMessages();
  } catch (error) {
    if (currentSession === session) showStatus(error.message);
  } finally {
    disableForm(messageForm, false);
  }
});

document.querySelector("#summarize-button").addEventListener("click", () => {
  executeTool("summarize_forum", "Summarize conversation", true);
});

useDraftButton.addEventListener("click", () => {
  if (messageForm.elements.content.value.trim()) {
    showStatus("Your composer already has a message. Clear it before using the draft.");
    return;
  }
  messageForm.elements.content.value = draft;
  selectTab(tabs[0]);
  messageForm.elements.content.focus();
  showStatus("Draft added. Review it, then select Send to publish.");
});

document.querySelector("#logout-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await request("/api/logout/", { method: "POST" });
    setAnonymous();
    showStatus("Signed out.");
    await refreshCsrfToken();
  } catch (error) {
    showStatus(error.message);
  } finally {
    button.disabled = false;
  }
});

async function initialize() {
  try {
    await refreshCsrfToken();
    const response = await fetch("/api/me/", { credentials: "same-origin" });
    if (response.status === 401) {
      setAnonymous();
      return;
    }
    if (!response.ok) throw new Error("Could not load your session. Please reload.");
    const data = await response.json();
    setAuthenticated(data.username);
  } catch (error) {
    showStatus(error.message);
  }
}

initialize();
setInterval(() => {
  if (!chatPanel.hidden && !document.hidden) {
    loadMessages().catch((error) => showStatus(error.message));
  }
}, 5000);
