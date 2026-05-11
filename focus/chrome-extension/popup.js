const DAEMON_URL = "http://127.0.0.1:7799";

async function req(path, method = "GET", body = null) {
  const res = await fetch(`${DAEMON_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}

async function refreshStatus() {
  const status = document.getElementById("status");
  try {
    const data = await req("/tasks/active");
    const a = data.activity || {};
    status.textContent = `${a.app_name || "N/A"} - ${a.window_title || "No activity yet"}`;
  } catch {
    status.textContent = "FOCUS daemon unavailable";
  }
}

async function showPending() {
  const box = document.getElementById("pending");
  try {
    const tasks = await req("/tasks/pending");
    if (!tasks.length) {
      box.textContent = "No pending tasks.";
      return;
    }
    box.innerHTML = tasks
      .map((t) => `#${t.id} [${t.status}] ${t.title}${t.blocked_reason ? ` - ${t.blocked_reason}` : ""}`)
      .join("<br>");
  } catch {
    box.textContent = "Could not fetch pending tasks.";
  }
}

async function createTask() {
  const title = prompt("Task title:");
  if (!title) return;
  const description = prompt("Description (optional):") || "";
  await req("/task/create", "POST", { title, description, priority: 3, estimated_minutes: 25 });
  await showPending();
}

async function markBlocked() {
  const taskId = Number(prompt("Task ID to block:"));
  if (!taskId) return;
  const reason = prompt("Reason:") || "";
  const dependency = prompt("Unblock condition:") || "";
  await req("/task/block", "POST", { task_id: taskId, reason, dependency });
  await showPending();
}

async function readPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  const response = await chrome.tabs.sendMessage(tab.id, { type: "FOCUS_READ_PAGE" });
  const summaryPrompt = `Summarize this page for my current task:\n\n${(response?.text || "").slice(0, 15000)}`;
  const result = await req("/chat", "POST", { message: summaryPrompt });
  alert(result.reply || "No response");
}

document.getElementById("newTask").addEventListener("click", createTask);
document.getElementById("markBlocked").addEventListener("click", markBlocked);
document.getElementById("pendingBtn").addEventListener("click", showPending);
document.getElementById("readPage").addEventListener("click", readPage);

refreshStatus();
