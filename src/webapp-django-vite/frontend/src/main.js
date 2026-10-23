import "./style.css";

const authPanel = document.querySelector("#auth-panel");
const chatPanel = document.querySelector("#chat-panel");
const authForm = document.querySelector("#auth-form");
const messageForm = document.querySelector("#message-form");
const messagesList = document.querySelector("#messages");
const status = document.querySelector("#status");
const usernameLabel = document.querySelector("#current-user");
const messageFilter = document.querySelector("#message-filter");
const mcpTokenInput = document.querySelector("#mcp-token");
const mcpTokenStatus = document.querySelector("#mcp-token-status");
const copyMcpTokenButton = document.querySelector("#copy-mcp-token");
let csrfToken = "";

function showStatus(message) {
  status.textContent = message;
}

async function request(path, options = {}) {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (method !== "GET") {
    headers.set("X-CSRFToken", csrfToken);
  }

  const response = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error ?? "Something went wrong.");
  }
  return data;
}

async function refreshCsrfToken() {
  const data = await request("/api/csrf/");
  csrfToken = data.csrfToken;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function renderMessages(messages) {
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
    if (message.labels?.length) {
      const labels = document.createElement("div");
      labels.className = "message-labels";
      for (const label of message.labels) {
        const badge = document.createElement("span");
        badge.className = "message-label";
        badge.textContent = label;
        labels.append(badge);
      }
      item.append(labels);
    }
    messagesList.append(item);
  }
  messagesList.scrollTop = messagesList.scrollHeight;
}

async function loadMessages() {
  const label = messageFilter.value;
  const query = label ? `?${new URLSearchParams({ label })}` : "";
  const data = await request(`/api/messages/${query}`);
  renderMessages(data.messages);
}

async function loadMcpTokenStatus() {
  const data = await request("/api/mcp-token/");
  mcpTokenStatus.textContent = data.configured
    ? "A token is configured. Generate a new one to rotate it."
    : "No token is configured.";
}

function setAuthenticated(username) {
  usernameLabel.textContent = `@${username}`;
  authPanel.hidden = true;
  chatPanel.hidden = false;
  showStatus("");
  loadMessages().catch((error) => showStatus(error.message));
  loadMcpTokenStatus().catch((error) => showStatus(error.message));
}

function setAnonymous() {
  chatPanel.hidden = true;
  authPanel.hidden = false;
  mcpTokenInput.value = "";
  mcpTokenInput.hidden = true;
  copyMcpTokenButton.hidden = true;
  mcpTokenStatus.textContent = "";
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(authForm);
  const mode = event.submitter.value;
  try {
    const data = await request(`/api/${mode}/`, {
      method: "POST",
      body: JSON.stringify({
        username: formData.get("username"),
        password: formData.get("password"),
      }),
    });
    authForm.reset();
    await refreshCsrfToken();
    setAuthenticated(data.username);
  } catch (error) {
    showStatus(error.message);
  }
});

messageForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = messageForm.elements.content;
  const content = input.value.trim();
  if (!content) {
    return;
  }
  try {
    await request("/api/messages/post/", {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    input.value = "";
    await loadMessages();
    showStatus("");
  } catch (error) {
    showStatus(error.message);
  }
});

messageFilter.addEventListener("change", () => {
  loadMessages().catch((error) => showStatus(error.message));
});

document.querySelector("#create-mcp-token").addEventListener("click", async () => {
  try {
    const data = await request("/api/mcp-token/create/", { method: "POST" });
    mcpTokenInput.value = data.token;
    mcpTokenInput.hidden = false;
    copyMcpTokenButton.hidden = false;
    mcpTokenStatus.textContent =
      "Copy this token now. It cannot be viewed again, and the previous token is revoked.";
  } catch (error) {
    showStatus(error.message);
  }
});

copyMcpTokenButton.addEventListener("click", async () => {
  try {
    await window.navigator.clipboard.writeText(mcpTokenInput.value);
    mcpTokenStatus.textContent = "Token copied to clipboard.";
  } catch {
    mcpTokenStatus.textContent = "Clipboard unavailable. Copy the token from the field.";
  }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    await request("/api/logout/", { method: "POST" });
    await refreshCsrfToken();
    setAnonymous();
  } catch (error) {
    showStatus(error.message);
  }
});

async function initialize() {
  try {
    await refreshCsrfToken();
    const data = await request("/api/me/");
    setAuthenticated(data.username);
  } catch (error) {
    if (error.message === "Authentication required.") {
      setAnonymous();
      return;
    }
    showStatus(error.message);
  }
}

initialize();
setInterval(() => {
  if (!chatPanel.hidden) {
    loadMessages().catch((error) => showStatus(error.message));
  }
}, 5000);
