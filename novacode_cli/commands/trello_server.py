"""HTTP server, REST API, and self-contained HTML page for the Trello task board.

The TrelloServer class starts a lightweight HTTP server (stdlib http.server)
in a background daemon thread, serving a single-page task board app with
three columns: Loaded (backlog), Processing (in progress), Done (completed).

REST API endpoints:
    GET  /api/tasks       — list all tasks
    POST /api/tasks       — create a new task (body: {"description": "..."})
    PATCH /api/tasks/<id> — update task status (body: {"status": "processing"})
    DELETE /api/tasks/<id>— remove a task

An asyncio.Queue bridge notifies the CLI when a task moves to "processing".
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import uuid
from datetime import UTC, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nova Task Board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg-deep: #0a0b0f;
    --bg-surface: #11131a;
    --bg-elevated: #181b24;
    --border-subtle: #1e2230;
    --border-mid: #2a2f42;
    --text-primary: #e2e4ed;
    --text-secondary: #8b90a5;
    --text-muted: #555a6e;
    --amber: #fbbf24;
    --amber-glow: rgba(251, 191, 36, 0.25);
    --cyan: #22d3ee;
    --cyan-glow: rgba(34, 211, 238, 0.25);
    --emerald: #34d399;
    --emerald-glow: rgba(52, 211, 153, 0.25);
    --radius: 12px;
    --radius-sm: 8px;
  }

  html { height: 100%; }

  body {
    font-family: 'Space Grotesk', system-ui, sans-serif;
    background: var(--bg-deep);
    color: var(--text-primary);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow-x: hidden;
  }

  /* Animated grid background */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(34, 211, 238, 0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(34, 211, 238, 0.03) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
    z-index: 0;
  }

  /* Subtle radial gradient overlay */
  body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: radial-gradient(ellipse 80% 60% at 50% -20%, rgba(34, 211, 238, 0.06), transparent 70%);
    pointer-events: none;
    z-index: 0;
  }

  /* Grain texture overlay */
  .grain {
    position: fixed;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0.035;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
    background-repeat: repeat;
    background-size: 256px 256px;
  }

  header {
    position: relative;
    z-index: 2;
    padding: 24px 28px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
    border-bottom: 1px solid var(--border-subtle);
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .logo-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--cyan), #0891b2);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    box-shadow: 0 0 20px var(--cyan-glow);
  }

  header h1 {
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.5px;
    background: linear-gradient(135deg, #e2e4ed, var(--cyan));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  header .subtitle {
    font-size: 13px;
    color: var(--text-secondary);
    font-weight: 400;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .server-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 20px;
    background: rgba(34, 211, 238, 0.08);
    border: 1px solid rgba(34, 211, 238, 0.15);
    color: var(--cyan);
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .server-badge .live-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--cyan);
    animation: pulse-dot 2s ease-in-out infinite;
  }

  @keyframes pulse-dot {
    0%, 100% { opacity: 1; box-shadow: 0 0 4px var(--cyan-glow); }
    50% { opacity: 0.4; box-shadow: 0 0 8px var(--cyan-glow); }
  }

  .add-task {
    position: relative;
    z-index: 2;
    display: flex;
    gap: 10px;
    padding: 16px 28px;
    border-bottom: 1px solid var(--border-subtle);
  }

  .add-task input {
    flex: 1;
    padding: 12px 16px;
    border: 1px solid var(--border-mid);
    border-radius: var(--radius-sm);
    background: var(--bg-surface);
    color: var(--text-primary);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 14px;
    outline: none;
    transition: all 0.25s ease;
  }

  .add-task input:focus {
    border-color: var(--cyan);
    box-shadow: 0 0 0 3px var(--cyan-glow);
  }

  .add-task input::placeholder {
    color: var(--text-muted);
  }

  .add-task button {
    padding: 12px 24px;
    border: none;
    border-radius: var(--radius-sm);
    background: linear-gradient(135deg, var(--cyan), #0891b2);
    color: #fff;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.25s ease;
    letter-spacing: 0.3px;
    position: relative;
    overflow: hidden;
  }

  .add-task button::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, transparent 40%, rgba(255,255,255,0.12) 100%);
    pointer-events: none;
  }

  .add-task button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 20px var(--cyan-glow);
  }

  .add-task button:active {
    transform: translateY(0);
  }

  .board {
    position: relative;
    z-index: 2;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    padding: 24px 28px;
    flex: 1;
    min-height: 0;
  }

  @media (max-width: 900px) {
    .board { grid-template-columns: 1fr; }
    header { flex-direction: column; align-items: flex-start; }
  }

  .column {
    background: var(--bg-surface);
    border-radius: var(--radius);
    border: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    min-height: 320px;
    backdrop-filter: blur(4px);
    transition: border-color 0.3s ease;
    position: relative;
  }

  .column:hover {
    border-color: var(--border-mid);
  }

  .column-header {
    padding: 16px 18px 14px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    border-bottom: 1px solid var(--border-subtle);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .column-header .count {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    padding: 2px 10px;
    border-radius: 12px;
    font-weight: 500;
  }

  .column-header.loaded { color: var(--amber); }
  .column-header.loaded .count {
    background: rgba(251, 191, 36, 0.1);
    color: var(--amber);
  }

  .column-header.processing { color: var(--cyan); }
  .column-header.processing .count {
    background: rgba(34, 211, 238, 0.1);
    color: var(--cyan);
  }

  .column-header.done { color: var(--emerald); }
  .column-header.done .count {
    background: rgba(52, 211, 153, 0.1);
    color: var(--emerald);
  }

  .task-list {
    flex: 1;
    padding: 10px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  /* Custom scrollbar */
  .task-list::-webkit-scrollbar {
    width: 4px;
  }
  .task-list::-webkit-scrollbar-track {
    background: transparent;
  }
  .task-list::-webkit-scrollbar-thumb {
    background: var(--border-mid);
    border-radius: 4px;
  }
  .task-list::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
  }

  .task-card {
    background: var(--bg-elevated);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
    cursor: pointer;
    transition: all 0.25s ease;
    position: relative;
    animation: card-enter 0.35s ease both;
  }

  @keyframes card-enter {
    from { opacity: 0; transform: translateY(8px) scale(0.97); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .task-card:hover {
    border-color: var(--border-mid);
    background: #1c1f2c;
    transform: translateY(-1px);
  }

  .task-card .task-text {
    font-size: 14px;
    line-height: 1.45;
    word-break: break-word;
    padding-right: 24px;
    font-weight: 450;
  }

  .task-card .task-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-muted);
    margin-top: 8px;
    letter-spacing: 0.2px;
  }

  .task-card .delete-btn {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 22px;
    height: 22px;
    border: none;
    background: none;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0;
    transition: all 0.2s ease;
  }

  .task-card:hover .delete-btn { opacity: 1; }
  .task-card .delete-btn:hover {
    color: #f87171;
    background: rgba(248, 113, 113, 0.1);
  }

  /* Status-specific card styles */
  .task-card.loaded {
    border-left: 3px solid var(--amber);
  }
  .task-card.loaded:hover {
    box-shadow: 0 0 16px var(--amber-glow);
  }

  .task-card.processing {
    border-left: 3px solid var(--cyan);
    background: linear-gradient(135deg, var(--bg-elevated), rgba(34, 211, 238, 0.03));
  }
  .task-card.processing:hover {
    box-shadow: 0 0 16px var(--cyan-glow);
  }
  .task-card.processing .task-text::after {
    content: '';
    display: inline-block;
    width: 6px;
    height: 6px;
    margin-left: 6px;
    border-radius: 50%;
    background: var(--cyan);
    animation: pulse-dot 1.2s ease-in-out infinite;
    vertical-align: middle;
  }

  .task-card.done {
    border-left: 3px solid var(--emerald);
    opacity: 0.8;
  }
  .task-card.done:hover {
    opacity: 1;
    box-shadow: 0 0 16px var(--emerald-glow);
  }

  .task-card .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    padding: 3px 8px;
    border-radius: 6px;
    margin-top: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
    letter-spacing: 0.3px;
    text-transform: uppercase;
  }

  .status-badge.amber {
    background: rgba(251, 191, 36, 0.1);
    color: var(--amber);
    border: 1px solid rgba(251, 191, 36, 0.15);
  }
  .status-badge.amber:hover {
    background: rgba(251, 191, 36, 0.18);
    box-shadow: 0 0 12px var(--amber-glow);
  }

  .status-badge.cyan {
    background: rgba(34, 211, 238, 0.1);
    color: var(--cyan);
    border: 1px solid rgba(34, 211, 238, 0.15);
  }
  .status-badge.cyan:hover {
    background: rgba(34, 211, 238, 0.18);
    box-shadow: 0 0 12px var(--cyan-glow);
  }

  .status-badge.emerald {
    background: rgba(52, 211, 153, 0.1);
    color: var(--emerald);
    border: 1px solid rgba(52, 211, 153, 0.15);
  }

  .empty-state {
    padding: 32px 16px;
    text-align: center;
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 400;
    letter-spacing: 0.3px;
  }

  .empty-state .empty-icon {
    font-size: 28px;
    margin-bottom: 8px;
    opacity: 0.5;
  }

  .status-bar {
    position: relative;
    z-index: 2;
    padding: 12px 28px;
    border-top: 1px solid var(--border-subtle);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    display: flex;
    gap: 24px;
    align-items: center;
  }

  .status-bar span {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .status-bar strong {
    color: var(--text-primary);
    font-weight: 500;
  }

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
  }
  .dot.amber { background: var(--amber); box-shadow: 0 0 6px var(--amber-glow); }
  .dot.cyan { background: var(--cyan); box-shadow: 0 0 6px var(--cyan-glow); }
  .dot.emerald { background: var(--emerald); box-shadow: 0 0 6px var(--emerald-glow); }

  .status-bar .divider {
    width: 1px;
    height: 14px;
    background: var(--border-subtle);
  }
</style>
</head>
<body>
<div class="grain"></div>

<header>
  <div class="header-left">
    <div class="logo-icon">N</div>
    <div>
      <h1>Task Board</h1>
      <span class="subtitle">Add tasks — the agent processes them one at a time</span>
    </div>
  </div>
  <div class="header-right">
    <div class="server-badge">
      <span class="live-dot"></span>
      LIVE
    </div>
  </div>
</header>

<div class="add-task">
  <input type="text" id="task-input" placeholder="Describe a task for the agent..." autofocus>
  <button id="add-btn">Add Task</button>
</div>

<div class="board">
  <div class="column">
    <div class="column-header loaded">
      <span>Loaded</span>
      <span class="count" id="loaded-count">0</span>
    </div>
    <div class="task-list" id="loaded-list"></div>
  </div>
  <div class="column">
    <div class="column-header processing">
      <span>Processing</span>
      <span class="count" id="processing-count">0</span>
    </div>
    <div class="task-list" id="processing-list"></div>
  </div>
  <div class="column">
    <div class="column-header done">
      <span>Done</span>
      <span class="count" id="done-count">0</span>
    </div>
    <div class="task-list" id="done-list"></div>
  </div>
</div>

<div class="status-bar">
  <span><span class="dot amber"></span> Loaded: <strong id="loaded-total">0</strong></span>
  <span class="divider"></span>
  <span><span class="dot cyan"></span> Processing: <strong id="processing-total">0</strong></span>
  <span class="divider"></span>
  <span><span class="dot emerald"></span> Done: <strong id="done-total">0</strong></span>
</div>

<script>
const API = '/api/tasks';
let tasks = [];

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function render() {
  const loaded = tasks.filter(t => t.status === 'loaded');
  const processing = tasks.filter(t => t.status === 'processing');
  const done = tasks.filter(t => t.status === 'done');

  document.getElementById('loaded-count').textContent = loaded.length;
  document.getElementById('processing-count').textContent = processing.length;
  document.getElementById('done-count').textContent = done.length;
  document.getElementById('loaded-total').textContent = loaded.length;
  document.getElementById('processing-total').textContent = processing.length;
  document.getElementById('done-total').textContent = done.length;

  renderList('loaded-list', loaded, 'loaded');
  renderList('processing-list', processing, 'processing');
  renderList('done-list', done, 'done');
}

function renderList(listId, items, status) {
  const el = document.getElementById(listId);
  if (items.length === 0) {
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">&#9744;</div>No tasks here</div>';
    return;
  }
  el.innerHTML = items.map((t, i) => {
    const nextStatus = status === 'loaded' ? 'processing' : status === 'processing' ? 'done' : null;
    const nextLabel = status === 'loaded' ? 'Start' : status === 'processing' ? 'Complete' : null;
    const badgeClass = status === 'loaded' ? 'amber' : status === 'processing' ? 'cyan' : 'emerald';
    return `<div class="task-card ${status}" data-id="${t.id}" style="animation-delay:${i * 0.05}s">
      <div class="task-text">${escapeHtml(t.description)}</div>
      <div class="task-meta">
        ${t.created_at ? 'Added ' + formatTime(t.created_at) : ''}
        ${t.completed_at ? '&middot; Done ' + formatTime(t.completed_at) : ''}
        ${t.result ? '&middot; Result available' : ''}
      </div>
      ${nextStatus
        ? `<span class="status-badge ${badgeClass}" data-action="move" data-target="${nextStatus}">&#9654; ${nextLabel}</span>`
        : `<span class="status-badge emerald">&#10003; Done</span>`}
      <button class="delete-btn" data-action="delete" title="Delete task">&times;</button>
    </div>`;
  }).join('');

  el.querySelectorAll('[data-action="move"]').forEach(badge => {
    badge.addEventListener('click', async (e) => {
      e.stopPropagation();
      const card = badge.closest('.task-card');
      const id = card.dataset.id;
      const target = badge.dataset.target;
      await moveTask(id, target);
    });
  });
  el.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const card = btn.closest('.task-card');
      const id = card.dataset.id;
      await deleteTask(id);
    });
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function fetchTasks() {
  try {
    const res = await fetch(API);
    tasks = await res.json();
    render();
  } catch (e) {
    console.error('Failed to fetch tasks:', e);
  }
}

async function addTask(description) {
  try {
    await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description })
    });
    await fetchTasks();
  } catch (e) {
    console.error('Failed to add task:', e);
  }
}

async function moveTask(id, status) {
  try {
    await fetch(`${API}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status })
    });
    await fetchTasks();
  } catch (e) {
    console.error('Failed to move task:', e);
  }
}

async function deleteTask(id) {
  try {
    await fetch(`${API}/${id}`, { method: 'DELETE' });
    await fetchTasks();
  } catch (e) {
    console.error('Failed to delete task:', e);
  }
}

document.getElementById('add-btn').addEventListener('click', () => {
  const input = document.getElementById('task-input');
  const text = input.value.trim();
  if (text) { addTask(text); input.value = ''; }
});
document.getElementById('task-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const input = document.getElementById('task-input');
    const text = input.value.trim();
    if (text) { addTask(text); input.value = ''; }
  }
});

fetchTasks();
setInterval(fetchTasks, 2000);
</script>
</body>
</html>"""


class TrelloRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Trello task board API and static page."""

    # Shared state — set by TrelloServer
    tasks: list[dict] = []
    lock: threading.Lock = threading.Lock()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server logging."""
        pass

    def _send_json(self, data: Any, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_html(self, html: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _read_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        return json.loads(body.decode("utf-8"))

    def _get_path_parts(self) -> list[str]:
        """Parse path into parts, handling /api/tasks/<id>."""
        path = self.path.rstrip("/")
        parts = path.split("/")
        # Remove empty strings from leading slash
        parts = [p for p in parts if p]
        return parts

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parts = self._get_path_parts()

        if self.path == "/" or self.path == "":
            self._send_html(HTML_PAGE)
            return

        if parts == ["api", "tasks"]:
            with self.lock:
                self._send_json(list(self.tasks))
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        parts = self._get_path_parts()

        if parts == ["api", "tasks"]:
            body = self._read_body()
            description = body.get("description", "").strip()
            if not description:
                self._send_json({"error": "description is required"}, 400)
                return

            task = {
                "id": str(uuid.uuid4()),
                "description": description,
                "status": "loaded",
                "created_at": datetime.now(UTC).isoformat(),
                "completed_at": None,
                "result": None,
            }

            with self.lock:
                self.tasks.append(task)

            self._send_json(task, 201)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_PATCH(self) -> None:
        parts = self._get_path_parts()

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks":
            task_id = parts[2]
            body = self._read_body()
            new_status = body.get("status", "").strip()

            if new_status not in ("loaded", "processing", "done"):
                self._send_json({"error": "status must be 'loaded', 'processing', or 'done'"}, 400)
                return

            with self.lock:
                for task in self.tasks:
                    if task["id"] == task_id:
                        old_status = task["status"]
                        task["status"] = new_status
                        if new_status == "done":
                            task["completed_at"] = datetime.now(UTC).isoformat()
                            task["result"] = body.get("result")
                        # Notify the asyncio queue if moving to processing
                        if new_status == "processing" and old_status != "processing":
                            q = getattr(TrelloRequestHandler, "_queue", None)
                            if q is not None:
                                try:
                                    # Use a thread-safe approach: schedule the put
                                    # We store the task ref and let the handler pick it up
                                    TrelloRequestHandler._pending_processing = task.copy()
                                except Exception:
                                    pass
                        self._send_json(task)
                        return

            self._send_json({"error": "Task not found"}, 404)
            return

        self._send_json({"error": "Not found"}, 404)

    def do_DELETE(self) -> None:
        parts = self._get_path_parts()

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "tasks":
            task_id = parts[2]

            with self.lock:
                for i, task in enumerate(self.tasks):
                    if task["id"] == task_id:
                        removed = self.tasks.pop(i)
                        self._send_json(removed)
                        return

            self._send_json({"error": "Task not found"}, 404)
            return

        self._send_json({"error": "Not found"}, 404)


# Class-level storage for the asyncio queue bridge
TrelloRequestHandler._queue: asyncio.Queue | None = None
TrelloRequestHandler._pending_processing: dict | None = None


class TrelloServer:
    """Lightweight HTTP server for the Trello task board.

    Runs in a background daemon thread. Exposes REST API endpoints and
    serves a self-contained HTML single-page app.

    An asyncio.Queue bridge notifies the CLI when a task moves to "processing".
    """

    def __init__(self) -> None:
        self._tasks: list[dict] = []
        self._lock = threading.Lock()
        self._task_queue: asyncio.Queue = asyncio.Queue()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0
        self.is_running: bool = False

    def _find_available_port(self) -> int:
        """Find a random available port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    async def start(self) -> int:
        """Start the HTTP server in a background daemon thread.

        Returns:
            The port number the server is listening on.
        """
        port = self._find_available_port()

        # Wire up shared state to the handler class
        TrelloRequestHandler.tasks = self._tasks
        TrelloRequestHandler.lock = self._lock
        TrelloRequestHandler._queue = self._task_queue
        TrelloRequestHandler._pending_processing = None

        self._server = HTTPServer(("127.0.0.1", port), TrelloRequestHandler)
        self.port = port
        self.is_running = True

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="trello-server",
        )
        self._thread.start()

        return port

    def stop(self) -> None:
        """Stop the HTTP server."""
        self.is_running = False
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    async def get_next_processing_task(self) -> dict | None:
        """Wait briefly for a task that entered processing state.

        Returns:
            The task dict if one is available, or None on timeout.
        """
        # First check if there's a pending processing notification from the HTTP thread
        pending = TrelloRequestHandler._pending_processing
        if pending is not None:
            TrelloRequestHandler._pending_processing = None
            return pending

        try:
            return await asyncio.wait_for(self._task_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            return None

    async def mark_done(self, task_id: str, result: str | None = None) -> None:
        """Mark a task as done via the API.

        This sends a PATCH request to the local server to update the task status.
        """
        import json
        import urllib.request

        url = f"http://127.0.0.1:{self.port}/api/tasks/{task_id}"
        body: dict[str, str] = {"status": "done"}
        if result:
            body["result"] = result

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="PATCH",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            # Fallback: update directly
            with self._lock:
                for task in self._tasks:
                    if task["id"] == task_id:
                        task["status"] = "done"
                        task["completed_at"] = datetime.now(UTC).isoformat()
                        task["result"] = result
                        break

    def get_task_counts(self) -> dict[str, int]:
        """Get the count of tasks in each status.

        Returns:
            Dict with keys 'loaded', 'processing', 'done'.
        """
        counts: dict[str, int] = {"loaded": 0, "processing": 0, "done": 0}
        with self._lock:
            for task in self._tasks:
                status = task.get("status", "loaded")
                if status in counts:
                    counts[status] += 1
        return counts

    def get_processing_task(self) -> dict | None:
        """Get the currently processing task, if any.

        Returns:
            The task dict if one is processing, or None.
        """
        with self._lock:
            for task in self._tasks:
                if task.get("status") == "processing":
                    return task
        return None

    def pop_next_loaded_task(self) -> dict | None:
        """Pop the next 'loaded' task and mark it as 'processing'.

        Returns:
            The task dict if one was available, or None.
        """
        with self._lock:
            for task in self._tasks:
                if task.get("status") == "loaded":
                    task["status"] = "processing"
                    return task.copy()
        return None
