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
    """Return a self-contained dark-themed chat UI (Claude-inspired)."""
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Nova Chat</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    height: 100vh; display: flex; flex-direction: column;
  }
  header {
    background: #16213e;
    padding: 16px 24px;
    border-bottom: 1px solid #ef4444;
    display: flex; align-items: center; gap: 12px;
    flex-shrink: 0;
  }
  header h1 {
    font-size: 18px; font-weight: 600;
    color: #ef4444;
  }
  header span { color: #9ca3af; font-size: 13px; }
  #messages {
    flex: 1; overflow-y: auto; padding: 24px;
    display: flex; flex-direction: column; gap: 16px;
  }
  .message {
    max-width: 80%; padding: 12px 16px;
    border-radius: 8px; line-height: 1.6;
    font-size: 14px; white-space: pre-wrap; word-wrap: break-word;
  }
  .message.user {
    align-self: flex-end;
    background: #ef4444; color: #fff;
    border-bottom-right-radius: 2px;
  }
  .message.assistant {
    align-self: flex-start;
    background: #16213e; color: #e0e0e0;
    border: 1px solid #2a2a4a;
    border-bottom-left-radius: 2px;
  }
  .message.assistant p { margin: 0 0 8px; }
  .message.assistant p:last-child { margin-bottom: 0; }
  .message.assistant pre {
    background: #0f0f23 !important;
    border-radius: 6px; padding: 12px; overflow-x: auto;
    margin: 8px 0;
  }
  .message.assistant code { font-size: 13px; }
  .message.assistant ul, .message.assistant ol {
    padding-left: 20px; margin: 4px 0;
  }
  .message.assistant blockquote {
    border-left: 3px solid #ef4444;
    padding-left: 12px; margin: 8px 0;
    color: #9ca3af;
  }
  .typing-indicator {
    align-self: flex-start;
    display: flex; gap: 4px;
    padding: 12px 16px;
    background: #16213e;
    border-radius: 8px; border: 1px solid #2a2a4a;
    border-bottom-left-radius: 2px;
  }
  .typing-indicator span {
    width: 8px; height: 8px; border-radius: 50%;
    background: #ef4444; display: inline-block;
    animation: bounce 1.4s infinite ease-in-out both;
  }
  .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
  .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
  .typing-indicator span:nth-child(3) { animation-delay: 0s; }
  @keyframes bounce {
    0%, 80%, 100% { transform: scale(0); }
    40% { transform: scale(1); }
  }
  .error-msg {
    align-self: center; color: #f87171; font-size: 13px;
    padding: 8px 16px;
    background: #2a1a1a; border-radius: 6px;
  }
  #input-area {
    display: flex; gap: 8px; padding: 16px 24px;
    background: #16213e; border-top: 1px solid #2a2a4a;
    flex-shrink: 0;
  }
  #input-area textarea {
    flex: 1; padding: 10px 14px; border-radius: 8px;
    border: 1px solid #2a2a4a; background: #0f0f23;
    color: #e0e0e0; font-size: 14px; font-family: inherit;
    resize: none; outline: none; min-height: 42px; max-height: 200px;
  }
  #input-area textarea:focus { border-color: #ef4444; }
  #input-area button {
    padding: 10px 20px; border-radius: 8px; border: none;
    background: #ef4444; color: #fff; font-size: 14px; font-weight: 500;
    cursor: pointer; transition: background 0.2s;
  }
  #input-area button:hover { background: #dc2626; }
  #input-area button:disabled { opacity: 0.5; cursor: not-allowed; }
  #status-bar {
    padding: 4px 24px; font-size: 12px; color: #6b7280;
    background: #0f0f23; text-align: center; flex-shrink: 0;
  }
  .welcome {
    text-align: center; color: #6b7280; margin: auto;
    padding: 40px 20px;
  }
  .welcome h2 { color: #ef4444; margin-bottom: 8px; }
  .welcome p { font-size: 14px; line-height: 1.6; }
</style>
</head>
<body>
<header>
  <h1>Nova</h1>
  <span>— Agentic Coding Assistant</span>
</header>
<div id="messages">
  <div class="welcome">
    <h2>Welcome to Nova</h2>
    <p>Ask me anything — coding, architecture, research, or just a question.<br>
    I'll respond with formatted Markdown and code highlighting.</p>
  </div>
</div>
<div id="input-area">
  <textarea id="input" rows="1" placeholder="Type your message..." autofocus></textarea>
  <button id="send-btn">Send</button>
</div>
<div id="status-bar"></div>

<script>
const $ = id => document.getElementById(id);
const messages = $('messages');
const input = $('input');
const sendBtn = $('send-btn');
const statusBar = $('status-bar');

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function addMessage(text, role) {
  const div = document.createElement('div');
  div.className = 'message ' + role;
  if (role === 'assistant') {
    div.innerHTML = marked.parse(text);
    div.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
  } else {
    div.textContent = text;
  }
  // Remove welcome message on first interaction
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
  input.disabled = true;
  sendBtn.disabled = true;

  addMessage(text, 'user');
  showTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    hideTyping();
    // Highlight the status — red on error, dim on success
    setStatus(res.ok ? '✓ Response received' : '✗ Error: ' + (data.error || 'Unknown error'));
    if (res.ok) {
      addMessage(data.reply, 'assistant');
    } else {
      addMessage(data.error || 'Request failed', 'error');
    }
  } catch (err) {
    hideTyping();
    setStatus('✗ Network error');
    addMessage('Network error: ' + err.message, 'error');
  }

  input.disabled = false;
  sendBtn.disabled = false;
  input.focus();
}

// Auto-resize textarea
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
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
            return f"Error: {event.text}"
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
# Command handler
# ---------------------------------------------------------------------------

async def handle_chat_command(session_state) -> bool:
    """Handle the /chat command — start or stop the web chat UI.

    Subcommands:
      /chat       — start the server (or bring existing to foreground)
      /chat stop  — stop the running server
    """
    global _server, _server_thread, _server_port

    # If the server is already running, stop it if requested.
    if _server is not None:
        console.print()
        console.print(
            f"[green]Chat UI already running at [bold]http://localhost:{_server_port}[/bold][/green]"
        )
        webbrowser.open(f"http://localhost:{_server_port}")
        return True

    port = _find_available_port(8000)
    _server_port = port

    _server = HTTPServer(("localhost", port), _ChatHandler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, daemon=True, name="chat-http-server"
    )
    _server_thread.start()

    url = f"http://localhost:{port}"
    console.print()
    console.print(f"[bold {COLORS['primary']}]╔══ Nova Chat ══╗[/bold {COLORS['primary']}]")
    console.print(f"[green]✓ Chat UI started at [bold]{url}[/bold][/green]")
    webbrowser.open(url)
    console.print(f"[dim]  Type /chat stop to stop the server.[/dim]")
    console.print()
    return True


async def handle_chat_stop_command(session_state) -> bool:
    """Stop the running chat server."""
    global _server, _server_thread, _server_port

    if _server is None:
        console.print("[yellow]Chat server is not running.[/yellow]")
        return True

    console.print("[dim]Shutting down chat server...[/dim]")
    _server.shutdown()
    _server.server_close()
    _server = None
    _server_thread = None
    _server_port = None
    console.print("[green]✓ Chat server stopped.[/green]")
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    """Register the /chat command."""
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        global _agent, _assistant_id, _session_state, _main_loop

        # Store references for the background server thread
        _agent = ctx.agent
        _assistant_id = ctx.assistant_id
        _session_state = ctx.session_state
        _main_loop = asyncio.get_running_loop()

        args = (ctx.cmd_args or "").strip()
        if args == "stop":
            return await handle_chat_stop_command(ctx.session_state)
        else:
            return await handle_chat_command(ctx.session_state)

    registry.register("chat", _handle)