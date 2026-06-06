"""Handler for /chat command — launches a local web chat UI.

The server runs in a background thread using Python's built-in
``http.server.ThreadingHTTPServer`` and hooks into the same LangGraph
agent from the CLI session via ``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from novacode_cli.config.config import COLORS, console
from novacode_cli import ui_events as ev

# ---------------------------------------------------------------------------
# Module-level state shared with the background HTTP server thread.
# Set by handle_chat_command before the server thread starts.
# ---------------------------------------------------------------------------

_agent: Any = None
_assistant_id: str | None = None
_session_state: Any = None
_main_loop: asyncio.AbstractEventLoop | None = None

_server: HTTPServer | None = None
_server_thread: threading.Thread | None = None
_server_port: int | None = None

_agent_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Embedded HTML chat page
# ---------------------------------------------------------------------------

def _make_chat_html() -> str:
    """Return a self-contained dark editorial-chat UI (Crimson Archive aesthetic)."""
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Nova — Agentic Coding</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=Playfair+Display:ital,wght@0,500;0,700;1,500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  :root {
    --crimson: #a21c30;
    --crimson-light: #d43b52;
    --charcoal: #1a1614;
    --charcoal-2: #231f1c;
    --charcoal-3: #2d2824;
    --cream: #efe9e3;
    --cream-muted: #b5ada3;
    --cream-dim: #7d756b;
    --gold: #b8860b;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--charcoal);
    color: var(--cream);
    height: 100vh; display: flex; flex-direction: column;
    background-image:
      radial-gradient(ellipse at 20% 50%, rgba(162,28,48,0.06) 0%, transparent 60%),
      radial-gradient(ellipse at 80% 20%, rgba(162,28,48,0.04) 0%, transparent 50%),
      repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(255,255,255,0.007) 2px, rgba(255,255,255,0.007) 4px);
    position: relative;
  }
  body::before {
    content: '';
    position: fixed; inset: 0;
    background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.035'/%3E%3C/svg%3E");
    pointer-events: none; z-index: 999;
  }
  header {
    padding: 20px 32px 16px;
    display: flex; align-items: baseline; gap: 14px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--charcoal-3);
    position: relative;
  }
  header::after {
    content: '';
    position: absolute; bottom: -1px; left: 32px;
    width: 60px; height: 2px;
    background: var(--crimson);
  }
  header h1 {
    font-family: 'Playfair Display', serif;
    font-weight: 700; font-size: 20px; font-style: italic;
    color: var(--cream);
    letter-spacing: 0.02em;
  }
  header span {
    font-size: 12px; color: var(--cream-dim);
    text-transform: uppercase; letter-spacing: 0.15em;
    font-weight: 400;
  }
  #messages {
    flex: 1; overflow-y: auto; padding: 28px 32px;
    display: flex; flex-direction: column; gap: 20px;
    scroll-behavior: smooth;
  }
  #messages::-webkit-scrollbar { width: 6px; }
  #messages::-webkit-scrollbar-track { background: transparent; }
  #messages::-webkit-scrollbar-thumb { background: var(--charcoal-3); border-radius: 3px; }
  .message {
    max-width: 78%; padding: 16px 20px;
    line-height: 1.65; font-size: 14px;
    white-space: pre-wrap; word-wrap: break-word;
    animation: msgIn 0.35s ease-out both;
    position: relative;
  }
  @keyframes msgIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .message.user {
    align-self: flex-end;
    background: var(--crimson);
    color: #fff;
    padding: 14px 20px;
    border-radius: 4px 4px 2px 4px;
  }
  .message.user::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent 10%, rgba(255,255,255,0.2) 50%, transparent 90%);
  }
  .message.assistant {
    align-self: flex-start;
    background: var(--charcoal-2);
    border-left: 3px solid var(--crimson);
    border-radius: 0 4px 4px 0;
    color: var(--cream);
  }
  .message.assistant p { margin: 0 0 10px; }
  .message.assistant p:last-child { margin-bottom: 0; }
  .message.assistant a {
    color: var(--crimson-light);
    text-decoration: underline; text-underline-offset: 2px;
  }
  .message.assistant a:hover { color: var(--crimson); }
  .message.assistant strong { color: #fff; font-weight: 600; }
  .message.assistant pre {
    background: #0d0b09 !important;
    border-radius: 3px; padding: 14px; overflow-x: auto;
    margin: 12px 0; border: 1px solid var(--charcoal-3);
    font-size: 12.5px;
  }
  .message.assistant pre code {
    background: none !important; padding: 0 !important;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }
  .message.assistant code {
    background: rgba(162,28,48,0.12);
    padding: 1px 6px; border-radius: 3px;
    font-size: 13px; color: var(--crimson-light);
  }
  .message.assistant ul, .message.assistant ol {
    padding-left: 22px; margin: 6px 0;
  }
  .message.assistant li { margin: 4px 0; }
  .message.assistant blockquote {
    border-left: 3px solid var(--crimson);
    padding: 8px 16px; margin: 12px 0;
    color: var(--cream-muted);
    background: rgba(162,28,48,0.05);
    border-radius: 0 3px 3px 0;
  }
  .message.assistant hr {
    border: none; border-top: 1px solid var(--charcoal-3);
    margin: 16px 0;
  }
  .message.assistant table {
    border-collapse: collapse; width: 100%;
    margin: 12px 0; font-size: 13px;
  }
  .message.assistant th, .message.assistant td {
    border: 1px solid var(--charcoal-3);
    padding: 8px 12px; text-align: left;
  }
  .message.assistant th {
    background: var(--charcoal); color: var(--cream);
    font-weight: 600;
  }
  /* Typing indicator — refined pulse */
  .typing-indicator {
    align-self: flex-start;
    display: flex; align-items: center; gap: 5px;
    padding: 16px 20px;
    border-left: 3px solid var(--crimson);
    background: var(--charcoal-2);
    border-radius: 0 4px 4px 0;
    animation: msgIn 0.35s ease-out both;
  }
  .typing-indicator span {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--cream-dim);
    display: inline-block;
    animation: typePulse 1.5s infinite ease-in-out both;
  }
  .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
  .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
  .typing-indicator span:nth-child(3) { animation-delay: 0s; }
  @keyframes typePulse {
    0%, 80%, 100% { transform: scale(0.6); opacity: 0.3; }
    40% { transform: scale(1); opacity: 1; background: var(--crimson); }
  }
  .error-msg {
    align-self: center; color: var(--crimson-light); font-size: 13px;
    padding: 10px 20px; text-align: center;
    background: rgba(162,28,48,0.08);
    border-radius: 4px; border: 1px solid rgba(162,28,48,0.2);
    animation: msgIn 0.35s ease-out both;
  }
  #input-area {
    display: flex; gap: 10px; padding: 16px 32px 20px;
    border-top: 1px solid var(--charcoal-3);
    flex-shrink: 0; align-items: flex-end;
    background: var(--charcoal);
  }
  #input-area textarea {
    flex: 1; padding: 12px 16px;
    border: 1px solid var(--charcoal-3);
    background: var(--charcoal-2);
    color: var(--cream);
    font-size: 14px; font-family: 'DM Sans', sans-serif;
    resize: none; outline: none;
    min-height: 46px; max-height: 180px;
    transition: border-color 0.25s, box-shadow 0.25s;
    border-radius: 4px;
  }
  #input-area textarea::placeholder { color: var(--cream-dim); }
  #input-area textarea:focus {
    border-color: var(--crimson);
    box-shadow: 0 0 0 1px rgba(162,28,48,0.2);
  }
  #input-area textarea:disabled { opacity: 0.5; }
  #input-area button {
    padding: 12px 22px; border-radius: 4px; border: none;
    background: var(--crimson); color: #fff;
    font-size: 13px; font-weight: 500;
    font-family: 'DM Sans', sans-serif;
    cursor: pointer;
    transition: background 0.2s, transform 0.15s;
    letter-spacing: 0.04em; text-transform: uppercase;
    min-height: 46px;
  }
  #input-area button:hover { background: var(--crimson-light); transform: translateY(-1px); }
  #input-area button:active { transform: translateY(0); }
  #input-area button:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }
  #status-bar {
    padding: 6px 32px; font-size: 11px; color: var(--cream-dim);
    background: var(--charcoal-2);
    text-align: center; flex-shrink: 0;
    text-transform: uppercase; letter-spacing: 0.08em;
    border-top: 1px solid var(--charcoal-3);
  }
  /* Welcome screen — editorial */
  .welcome {
    text-align: center; margin: auto;
    padding: 60px 32px; max-width: 480px;
    animation: msgIn 0.6s ease-out both;
  }
  .welcome h2 {
    font-family: 'Playfair Display', serif;
    font-weight: 700; font-size: 28px; font-style: italic;
    color: var(--cream); margin-bottom: 6px;
  }
  .welcome .divider {
    width: 40px; height: 2px;
    background: var(--crimson); margin: 16px auto;
  }
  .welcome p {
    font-size: 13.5px; line-height: 1.7;
    color: var(--cream-muted);
    margin-bottom: 8px;
  }
  .welcome .kbd {
    display: inline-block;
    padding: 2px 8px;
    border: 1px solid var(--charcoal-3);
    border-radius: 3px;
    font-size: 11px; font-family: 'DM Sans', sans-serif;
    color: var(--cream-dim);
  }
</style>
</head>
<body>
<header>
  <h1>Nova</h1>
  <span>Agentic Coding</span>
</header>
<div id="messages">
  <div class="welcome">
    <h2>Nova</h2>
    <div class="divider"></div>
    <p>Your agentic coding assistant. Ask me anything — architecture, implementation, research, or debugging.</p>
    <p><span class="kbd">Enter</span> to send &nbsp;·&nbsp; <span class="kbd">Shift+Enter</span> for newline</p>
  </div>
</div>
<div id="input-area">
  <textarea id="input" rows="1" placeholder="Type your message…" autofocus></textarea>
  <button id="send-btn">Send</button>
</div>
<div id="status-bar">ready</div>

<script>
const $ = id => document.getElementById(id);
const messages = $('messages');
const input = $('input');
const sendBtn = $('send-btn');
const statusBar = $('status-bar');

function addMessage(text, role) {
  const div = document.createElement('div');
  div.className = 'message ' + role;
  if (role === 'assistant') {
    div.innerHTML = marked.parse(text);
    div.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
  } else {
    div.textContent = text;
  }
  const welcome = messages.querySelector('.welcome');
  if (welcome) welcome.remove();
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function showTyping() {
  const div = document.createElement('div');
  div.className = 'typing-indicator';
  div.id = 'typing';
  div.innerHTML = '<span></span><span></span><span></span>';
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}

function hideTyping() {
  const el = $('typing');
  if (el) el.remove();
}

function setStatus(msg) { statusBar.textContent = msg; }

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  input.disabled = true;
  sendBtn.disabled = true;

  addMessage(text, 'user');
  showTyping();
  setStatus('thinking…');

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    hideTyping();
    if (res.ok) {
      setStatus('ready');
      addMessage(data.reply, 'assistant');
    } else {
      setStatus('error — ' + (data.error || 'unknown'));
      addMessage(data.error || 'Request failed', 'error-msg');
    }
  } catch (err) {
    hideTyping();
    setStatus('connection error');
    addMessage('Network error: ' + err.message, 'error-msg');
  }

  input.disabled = false;
  sendBtn.disabled = false;
  input.focus();
}

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
sendBtn.addEventListener('click', sendMessage);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _ChatHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the chat server."""

    def log_message(self, format, *args):
        """Silence the default stderr logging; we use Nova's console."""
        pass

    # ---- GET ----

    def do_GET(self):
        if self.path == "/":
            self._serve_html()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        html = _make_chat_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    # ---- POST ----

    def do_POST(self):
        if self.path == "/api/chat":
            self._handle_chat()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_chat(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        data = json.loads(body)
        user_msg = data.get("message", "")

        if not user_msg.strip():
            self._json_response(400, {"error": "Message is required"})
            return

        loop = _main_loop
        if loop is None or not loop.is_running():
            self._json_response(503, {"error": "Agent event loop is not running"})
            return

        future = asyncio.run_coroutine_threadsafe(
            _call_agent(user_msg), loop
        )

        try:
            reply = future.result(timeout=120)
            self._json_response(200, {"reply": reply})
        except asyncio.TimeoutError:
            self._json_response(504, {"error": "Agent did not respond within 120 seconds"})
        except Exception as exc:
            self._json_response(500, {"error": f"Agent error: {exc}"})

    def _json_response(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Agent call
# ---------------------------------------------------------------------------

async def _call_agent(message: str) -> str:
    """Send a message to the agent and return the full text response."""
    from novacode_cli.agent_stream import run_agent_stream

    with _agent_lock:
        agent = _agent
        assistant_id = _assistant_id
        session_state = _session_state

    if agent is None:
        return "Error: Agent not available. Start a CLI session first."

    response_chunks: list[str] = []

    async for event in run_agent_stream(
        message,
        agent,
        assistant_id,
        session_state,
    ):
        if isinstance(event, ev.TextDelta):
            response_chunks.append(event.text)
        elif isinstance(event, ev.AssistantMessage):
            response_chunks.append(event.text)
        elif isinstance(event, ev.Error):
            return f"Error: {event.message}"
        elif isinstance(event, ev.Cancelled):
            return "Response was cancelled."
        # Done — stop iterating gracefully (the generator ends on its own)

    return "".join(response_chunks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_available_port(start_port: int = 8000, max_attempts: int = 100) -> int:
    """Find an available port starting from *start_port*."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No available ports in range {start_port}-{start_port + max_attempts}"
    )


# ---------------------------------------------------------------------------
# Server lifecycle (shared by CLI handler and TUI)
# ---------------------------------------------------------------------------

def want_restart() -> bool:
    """Return True if the server should restart (state reset requested)."""
    return False


def is_server_running() -> bool:
    """Check if the chat server is currently running."""
    return _server is not None


def get_server_url() -> str | None:
    """Return the URL of the running server, or None."""
    if _server_port is None:
        return None
    return f"http://localhost:{_server_port}"


def set_agent_refs(
    agent: Any,
    assistant_id: str | None,
    session_state: Any,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Store agent references for the background HTTP server thread."""
    global _agent, _assistant_id, _session_state, _main_loop
    _agent = agent
    _assistant_id = assistant_id
    _session_state = session_state
    _main_loop = loop


def start_chat_server() -> str:
    """Start the HTTP chat server in a daemon thread.

    Must have called :func:`set_agent_refs` first.

    Returns:
        The URL the server is listening on.

    Raises:
        RuntimeError: If no available port is found.
    """
    global _server, _server_thread, _server_port

    if _server is not None:
        assert _server_port is not None
        return f"http://localhost:{_server_port}"

    port = _find_available_port(8000)
    _server_port = port

    _server = HTTPServer(("localhost", port), _ChatHandler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, daemon=True, name="chat-http-server"
    )
    _server_thread.start()

    return f"http://localhost:{port}"


def stop_chat_server() -> bool:
    """Stop the running chat server.

    Returns:
        True if the server was stopped, False if it wasn't running.
    """
    global _server, _server_thread, _server_port

    if _server is None:
        return False

    _server.shutdown()
    _server.server_close()
    _server = None
    _server_thread = None
    _server_port = None
    return True


# ---------------------------------------------------------------------------
# CLI command handler
# ---------------------------------------------------------------------------

async def handle_chat_command() -> bool:
    """Handle the /chat command — start the web chat UI.

    For the CLI (non-TUI) entry point.
    """
    if is_server_running():
        url = get_server_url()
        assert url is not None
        console.print()
        console.print(
            f"[green]Chat UI already running at [bold]{url}[/bold][/green]"
        )
        webbrowser.open(url)
        return True

    url = start_chat_server()
    console.print()
    console.print(f"[bold {COLORS['primary']}]╔══ Nova Chat ══╗[/bold {COLORS['primary']}]")
    console.print(f"[green]✓ Chat UI started at [bold]{url}[/bold][/green]")
    webbrowser.open(url)
    console.print(f"[dim]  Type /chat stop to stop the server.[/dim]")
    console.print()
    return True


async def handle_chat_stop_command() -> bool:
    """Handle the /chat stop command — stop the web chat UI.

    For the CLI (non-TUI) entry point.
    """
    if not is_server_running():
        console.print("[yellow]Chat server is not running.[/yellow]")
        return True

    console.print("[dim]Shutting down chat server...[/dim]")
    stop_chat_server()
    console.print("[green]✓ Chat server stopped.[/green]")
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    """Register the /chat command."""
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        set_agent_refs(
            ctx.agent,
            ctx.assistant_id,
            ctx.session_state,
            asyncio.get_running_loop(),
        )

        args = (ctx.cmd_args or "").strip()
        if args == "stop":
            return await handle_chat_stop_command()
        else:
            return await handle_chat_command()

    registry.register("chat", _handle)