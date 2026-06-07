"""Handler for /chat command — launches a local **Council** web UI.

The ``/chat`` web UI runs a *council of agents*: five personas debate a topic
chatroom-style, then score each other; the highest-scoring answer is the
verdict. The server runs in a background thread
(``http.server.ThreadingHTTPServer``) and streams the council over **Server-Sent
Events** to the browser, driving the same LangGraph session's configured model
via ``asyncio.run_coroutine_threadsafe`` onto the CLI event loop.

The council logic itself lives in :mod:`novacode_cli.council`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from novacode_cli.config.config import COLORS, console

logger = logging.getLogger(__name__)

# Sentinel pushed onto the event queue when the council run finishes.
_STREAM_END = object()

# ---------------------------------------------------------------------------
# Module-level state shared with the background HTTP server thread.
# Set by set_agent_refs before the server thread starts.
# ---------------------------------------------------------------------------

_agent: Any = None
_assistant_id: str | None = None
_session_state: Any = None
_main_loop: asyncio.AbstractEventLoop | None = None

_server: ThreadingHTTPServer | None = None
_server_thread: threading.Thread | None = None
_server_port: int | None = None

# Only one council can be in session at a time (a single shared model/loop).
_run_lock = threading.Lock()

# Prior council rounds (this server's lifetime), so follow-up topics can build on
# the earlier discussion. Each round: {"topic", "transcript": [[name, text]...],
# "winner"}. Guarded by _run_lock (only one run mutates it at a time). Reset via
# GET /api/council/reset or when the server stops.
_council_history: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Embedded HTML council page
# ---------------------------------------------------------------------------

def _make_chat_html() -> str:
    """Return a self-contained dark editorial council UI (Crimson Archive)."""
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Nova — Council</title>
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
  }
  header {
    padding: 20px 32px 16px;
    display: flex; align-items: baseline; gap: 14px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--charcoal-3);
    position: relative;
  }
  header::after {
    content: ''; position: absolute; bottom: -1px; left: 32px;
    width: 60px; height: 2px; background: var(--crimson);
  }
  header h1 {
    font-family: 'Playfair Display', serif;
    font-weight: 700; font-size: 20px; font-style: italic;
    color: var(--cream); letter-spacing: 0.02em;
  }
  header span {
    font-size: 12px; color: var(--cream-dim);
    text-transform: uppercase; letter-spacing: 0.15em;
  }
  header .spacer { flex: 1; }
  #new-thread {
    background: transparent; color: var(--cream-muted);
    border: 1px solid var(--charcoal-3); border-radius: 4px;
    padding: 6px 12px; font-size: 11px; font-family: 'DM Sans', sans-serif;
    text-transform: uppercase; letter-spacing: 0.08em; cursor: pointer;
    transition: border-color 0.2s, color 0.2s;
  }
  #new-thread:hover { border-color: var(--crimson); color: var(--cream); }
  #messages {
    flex: 1; overflow-y: auto; padding: 28px 32px;
    display: flex; flex-direction: column; gap: 18px;
    scroll-behavior: smooth;
  }
  #messages::-webkit-scrollbar { width: 6px; }
  #messages::-webkit-scrollbar-thumb { background: var(--charcoal-3); border-radius: 3px; }

  .topic-banner {
    align-self: center; max-width: 80%;
    text-align: center; color: var(--cream-muted);
    font-family: 'Playfair Display', serif; font-style: italic; font-size: 17px;
    padding: 8px 20px; border-bottom: 1px solid var(--charcoal-3);
  }

  /* Agent message */
  .agent {
    max-width: 82%; align-self: flex-start;
    background: var(--charcoal-2);
    border-left: 3px solid var(--seat, var(--crimson));
    border-radius: 0 6px 6px 0;
    padding: 12px 18px; animation: msgIn 0.35s ease-out both;
  }
  .agent .who {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 6px; font-weight: 600; font-size: 13.5px;
    color: var(--seat, var(--cream));
  }
  .agent .who .avatar { font-size: 16px; }
  .agent .search-chip {
    font-size: 11.5px; color: var(--gold); margin-bottom: 6px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace; opacity: 0.9;
    word-break: break-word;
  }
  .agent .body { line-height: 1.6; font-size: 14px; color: var(--cream); }
  .agent .body p { margin: 0 0 8px; }
  .agent .body p:last-child { margin-bottom: 0; }
  .agent .body pre {
    background: #0d0b09 !important; border-radius: 3px; padding: 12px;
    overflow-x: auto; margin: 10px 0; border: 1px solid var(--charcoal-3);
    font-size: 12.5px;
  }
  .agent .body code {
    background: rgba(162,28,48,0.12); padding: 1px 6px; border-radius: 3px;
    font-size: 13px; color: var(--crimson-light);
  }
  .agent .body pre code { background: none !important; padding: 0 !important; }
  .agent.streaming .body::after {
    content: '▍'; color: var(--seat, var(--crimson-light));
    animation: caret 1s steps(1) infinite; margin-left: 1px;
  }
  @keyframes caret { 50% { opacity: 0; } }
  @keyframes msgIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

  /* Voting */
  .phase {
    align-self: center; color: var(--gold); font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.2em; font-weight: 600;
    margin: 10px 0 2px; display: flex; align-items: center; gap: 12px;
  }
  .phase::before, .phase::after {
    content: ''; height: 1px; width: 60px; background: var(--charcoal-3);
  }
  .vote-card {
    max-width: 82%; align-self: flex-start;
    background: var(--charcoal-2); border: 1px solid var(--charcoal-3);
    border-radius: 6px; padding: 10px 16px; font-size: 13px;
    animation: msgIn 0.3s ease-out both;
  }
  .vote-card .voter {
    font-weight: 600; color: var(--seat, var(--cream)); margin-bottom: 6px;
    display: flex; align-items: center; gap: 6px;
  }
  .vote-card .ballot {
    display: flex; justify-content: space-between; gap: 10px;
    padding: 3px 0; color: var(--cream-muted); border-top: 1px dashed var(--charcoal-3);
  }
  .vote-card .ballot:first-of-type { border-top: none; }
  .vote-card .ballot .pts {
    color: var(--gold); font-weight: 600; font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .vote-card .ballot .why { color: var(--cream-dim); font-size: 12px; }

  /* Verdict */
  .verdict {
    align-self: stretch; margin: 8px 0;
    background: linear-gradient(180deg, rgba(162,28,48,0.10), rgba(162,28,48,0.02));
    border: 1px solid var(--crimson); border-radius: 8px;
    padding: 18px 22px; animation: msgIn 0.4s ease-out both;
  }
  .verdict h3 {
    font-family: 'Playfair Display', serif; font-style: italic;
    font-size: 18px; color: var(--cream); margin-bottom: 12px;
    display: flex; align-items: center; gap: 10px;
  }
  .leaderboard { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
  .lb-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
  .lb-row .lb-name { width: 150px; color: var(--cream-muted); flex-shrink: 0; }
  .lb-row.win .lb-name { color: var(--cream); font-weight: 600; }
  .lb-bar { flex: 1; height: 8px; background: var(--charcoal-3); border-radius: 4px; overflow: hidden; }
  .lb-fill { height: 100%; background: var(--seat, var(--crimson)); border-radius: 4px; transition: width 0.6s ease; }
  .lb-row .lb-pts { width: 34px; text-align: right; color: var(--gold); font-weight: 600; font-variant-numeric: tabular-nums; }
  .verdict .winner-answer {
    border-top: 1px solid var(--charcoal-3); padding-top: 12px;
    line-height: 1.6; font-size: 14px; color: var(--cream);
  }
  .verdict .winner-answer pre { background: #0d0b09 !important; padding: 12px; border-radius: 3px; overflow-x: auto; }

  .error-msg {
    align-self: center; color: var(--crimson-light); font-size: 13px;
    padding: 10px 20px; text-align: center;
    background: rgba(162,28,48,0.08);
    border-radius: 4px; border: 1px solid rgba(162,28,48,0.2);
  }

  #input-area {
    display: flex; gap: 10px; padding: 16px 32px 20px;
    border-top: 1px solid var(--charcoal-3);
    flex-shrink: 0; align-items: flex-end; background: var(--charcoal);
  }
  #input-area textarea {
    flex: 1; padding: 12px 16px; border: 1px solid var(--charcoal-3);
    background: var(--charcoal-2); color: var(--cream);
    font-size: 14px; font-family: 'DM Sans', sans-serif;
    resize: none; outline: none; min-height: 46px; max-height: 180px;
    transition: border-color 0.25s, box-shadow 0.25s; border-radius: 4px;
  }
  #input-area textarea::placeholder { color: var(--cream-dim); }
  #input-area textarea:focus { border-color: var(--crimson); box-shadow: 0 0 0 1px rgba(162,28,48,0.2); }
  #input-area textarea:disabled { opacity: 0.5; }
  #input-area button {
    padding: 12px 24px; border-radius: 4px; border: none;
    background: var(--crimson); color: #fff; font-size: 13px; font-weight: 500;
    font-family: 'DM Sans', sans-serif; cursor: pointer;
    transition: background 0.2s, transform 0.15s;
    letter-spacing: 0.04em; text-transform: uppercase; min-height: 46px;
  }
  #input-area button:hover { background: var(--crimson-light); transform: translateY(-1px); }
  #input-area button:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }
  #status-bar {
    padding: 6px 32px; font-size: 11px; color: var(--cream-dim);
    background: var(--charcoal-2); text-align: center; flex-shrink: 0;
    text-transform: uppercase; letter-spacing: 0.08em;
    border-top: 1px solid var(--charcoal-3);
  }
  .welcome { text-align: center; margin: auto; padding: 60px 32px; max-width: 520px; animation: msgIn 0.6s ease-out both; }
  .welcome h2 { font-family: 'Playfair Display', serif; font-weight: 700; font-size: 28px; font-style: italic; color: var(--cream); margin-bottom: 6px; }
  .welcome .divider { width: 40px; height: 2px; background: var(--crimson); margin: 16px auto; }
  .welcome p { font-size: 13.5px; line-height: 1.7; color: var(--cream-muted); margin-bottom: 8px; }
  .welcome .seats { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 16px; }
  .welcome .seat { font-size: 12px; padding: 4px 10px; border: 1px solid var(--charcoal-3); border-radius: 20px; color: var(--cream-muted); }
</style>
</head>
<body>
<header>
  <h1>Nova</h1>
  <span>Council of Agents</span>
  <div class="spacer"></div>
  <button id="new-thread" title="Forget the prior discussion and start fresh">⟲ New thread</button>
</header>
<div id="messages">
  <div class="welcome">
    <h2>The Council Awaits</h2>
    <div class="divider"></div>
    <p>Present a topic and five advisors will debate it in turn — each reading the others — then score one another. The highest-scored answer becomes the verdict. Ask follow-ups and they'll remember the discussion; hit <b>New thread</b> to start fresh.</p>
    <div class="seats">
      <span class="seat">🏛️ Architect</span>
      <span class="seat">🛠️ Pragmatist</span>
      <span class="seat">🔍 Skeptic</span>
      <span class="seat">🚀 Innovator</span>
      <span class="seat">✂️ Minimalist</span>
    </div>
  </div>
</div>
<div id="input-area">
  <textarea id="input" rows="1" placeholder="Present a topic to the council…" autofocus></textarea>
  <button id="send-btn">Convene</button>
</div>
<div id="status-bar">ready</div>

<script>
const $ = id => document.getElementById(id);
const messages = $('messages');
const input = $('input');
const sendBtn = $('send-btn');
const statusBar = $('status-bar');

let es = null;
const agentEls = {};   // id -> {wrap, body, buf}
let agentMeta = {};    // id -> {name, avatar, color}

function setStatus(m) { statusBar.textContent = m; }
function atBottom() { return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 100; }
function scrollDown(force) { if (force || atBottom()) messages.scrollTop = messages.scrollHeight; }
function dropWelcome() { const w = messages.querySelector('.welcome'); if (w) w.remove(); }
function highlight(el) { el.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b)); }
function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }

function addError(text) {
  dropWelcome();
  const e = el('div', 'error-msg'); e.textContent = text;
  messages.appendChild(e); scrollDown(true);
}
function addPhase(text) {
  const e = el('div', 'phase'); e.textContent = text;
  messages.appendChild(e); scrollDown(true);
}

function startAgent(meta) {
  dropWelcome();
  const wrap = el('div', 'agent streaming');
  wrap.style.setProperty('--seat', meta.color || 'var(--crimson)');
  const who = el('div', 'who');
  const av = el('span', 'avatar'); av.textContent = meta.avatar || '•';
  const nm = el('span'); nm.textContent = meta.name || meta.id;
  who.appendChild(av); who.appendChild(nm);
  const body = el('div', 'body');
  wrap.appendChild(who); wrap.appendChild(body);
  messages.appendChild(wrap);
  agentEls[meta.id] = { wrap, body, buf: '' };
  scrollDown(true);
}

function deltaAgent(id, text) {
  const a = agentEls[id]; if (!a) return;
  a.buf += text;
  a.body.innerHTML = marked.parse(a.buf);
  highlight(a.body);
  scrollDown();
}

function finishAgent(id, text) {
  const a = agentEls[id]; if (!a) return;
  a.wrap.classList.remove('streaming');
  if (text) { a.body.innerHTML = marked.parse(text); highlight(a.body); }
  scrollDown();
}

function agentSearch(id, query) {
  const a = agentEls[id]; if (!a) return;
  const chip = el('div', 'search-chip');
  chip.textContent = '🔍 searched: ' + (query || '…');
  a.wrap.insertBefore(chip, a.body);
  scrollDown();
}

function renderVote(ev) {
  const card = el('div', 'vote-card');
  const meta = agentMeta[ev.voter] || {};
  card.style.setProperty('--seat', meta.color || 'var(--crimson)');
  const voter = el('div', 'voter');
  voter.textContent = (meta.avatar ? meta.avatar + ' ' : '') + (ev.voter_name || ev.voter) + ' scores:';
  card.appendChild(voter);
  if (!ev.scores || !ev.scores.length) {
    const b = el('div', 'ballot'); b.textContent = '(abstained)'; card.appendChild(b);
  }
  (ev.scores || []).forEach(s => {
    const row = el('div', 'ballot');
    const left = el('div');
    const nm = el('span'); nm.textContent = s.target_name;
    const why = el('div', 'why'); why.textContent = s.reason || '';
    left.appendChild(nm); left.appendChild(why);
    const pts = el('div', 'pts'); pts.textContent = s.score + '/10';
    row.appendChild(left); row.appendChild(pts);
    card.appendChild(row);
  });
  messages.appendChild(card);
  scrollDown();
}

function renderVerdict(ev) {
  const card = el('div', 'verdict');
  const h = el('h3');
  const wm = agentMeta[ev.winner_id] || {};
  h.textContent = '🏆 Verdict — ' + (wm.avatar ? wm.avatar + ' ' : '') + (ev.winner_name || '');
  card.appendChild(h);

  const totals = ev.totals || {};
  const max = Math.max(1, ...Object.values(totals));
  const board = el('div', 'leaderboard');
  Object.keys(totals).sort((a, b) => totals[b] - totals[a]).forEach(id => {
    const m = agentMeta[id] || {};
    const row = el('div', 'lb-row' + (id === ev.winner_id ? ' win' : ''));
    row.style.setProperty('--seat', m.color || 'var(--crimson)');
    const name = el('div', 'lb-name'); name.textContent = (m.avatar ? m.avatar + ' ' : '') + (m.name || id);
    const bar = el('div', 'lb-bar'); const fill = el('div', 'lb-fill');
    fill.style.width = Math.round((totals[id] / max) * 100) + '%';
    bar.appendChild(fill);
    const pts = el('div', 'lb-pts'); pts.textContent = totals[id];
    row.appendChild(name); row.appendChild(bar); row.appendChild(pts);
    board.appendChild(row);
  });
  card.appendChild(board);

  if (ev.answer) {
    const ans = el('div', 'winner-answer');
    ans.innerHTML = marked.parse(ev.answer); highlight(ans);
    card.appendChild(ans);
  }
  messages.appendChild(card);
  scrollDown(true);
}

function endRun() {
  if (es) { es.close(); es = null; }
  input.disabled = false; sendBtn.disabled = false; input.focus();
}

function convene() {
  const topic = input.value.trim();
  if (!topic || es) return;
  input.value = ''; input.style.height = 'auto';
  input.disabled = true; sendBtn.disabled = true;

  // fresh transcript per topic
  for (const k in agentEls) delete agentEls[k];
  agentMeta = {};

  dropWelcome();
  const banner = el('div', 'topic-banner'); banner.textContent = '“' + topic + '”';
  messages.appendChild(banner);
  setStatus('convening…'); scrollDown(true);

  es = new EventSource('/api/council?topic=' + encodeURIComponent(topic));

  es.addEventListener('council_start', e => {
    const d = JSON.parse(e.data);
    (d.agents || []).forEach(a => { agentMeta[a.id] = a; });
    setStatus('the council is deliberating…');
  });
  es.addEventListener('agent_start', e => {
    const d = JSON.parse(e.data);
    agentMeta[d.id] = d; startAgent(d);
    setStatus((d.name || 'an advisor') + ' is speaking…');
  });
  es.addEventListener('agent_delta', e => { const d = JSON.parse(e.data); deltaAgent(d.id, d.text); });
  es.addEventListener('agent_tool', e => { const d = JSON.parse(e.data); agentSearch(d.id, d.query); });
  es.addEventListener('agent_done', e => { const d = JSON.parse(e.data); finishAgent(d.id, d.text); });
  es.addEventListener('vote_start', e => { addPhase('The Vote'); setStatus('the advisors are scoring each other…'); });
  es.addEventListener('vote', e => { renderVote(JSON.parse(e.data)); });
  es.addEventListener('verdict', e => { renderVerdict(JSON.parse(e.data)); });
  es.addEventListener('council_error', e => {
    let m = 'The council failed.';
    try { m = JSON.parse(e.data).message || m; } catch (_) {}
    addError(m); setStatus('error');
  });
  es.addEventListener('done', e => { setStatus('the council has spoken'); endRun(); });
  es.onerror = () => {
    if (!es || es.readyState === EventSource.CLOSED) {
      setStatus('connection closed'); endRun();
    }
  };
}

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 180) + 'px';
});
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); convene(); }
});
sendBtn.addEventListener('click', convene);

const newThreadBtn = $('new-thread');
function newThread() {
  if (es) return;  // don't reset mid-run
  fetch('/api/council/reset').catch(() => {});
  messages.innerHTML = '';
  for (const k in agentEls) delete agentEls[k];
  agentMeta = {};
  const w = el('div', 'welcome');
  w.innerHTML = '<h2>Fresh Council</h2><div class="divider"></div>' +
    '<p>Prior discussion cleared. Present a new topic to convene the council.</p>';
  messages.appendChild(w);
  setStatus('ready');
  input.focus();
}
newThreadBtn.addEventListener('click', newThread);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _ChatHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the council server."""

    def log_message(self, format, *args):  # noqa: A002 - signature from stdlib
        """Silence the default stderr logging; we use Nova's console."""

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_html()
        elif parsed.path == "/api/council":
            qs = parse_qs(parsed.query)
            topic = (qs.get("topic") or [""])[0]
            self._stream_council(topic)
        elif parsed.path == "/api/council/reset":
            self._reset_history()
        else:
            self.send_response(404)
            self.end_headers()

    def _reset_history(self) -> None:
        """Clear the council's cross-round history (start a fresh thread)."""
        global _council_history
        with _run_lock:
            _council_history = []
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _serve_html(self):
        html = _make_chat_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(html.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ---- SSE council stream ----

    def _stream_council(self, topic: str) -> None:
        """Run a council over *topic* and stream it to the browser as SSE."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        loop = _main_loop
        if loop is None or not loop.is_running():
            self._sse("council_error", {"message": "Agent event loop is not running"})
            self._sse("done", {})
            return
        if not topic.strip():
            self._sse("council_error", {"message": "A topic is required"})
            self._sse("done", {})
            return
        if not _run_lock.acquire(blocking=False):
            self._sse("council_error", {"message": "The council is already in session"})
            self._sse("done", {})
            return

        try:
            self._pump_council(topic, loop)
        finally:
            _run_lock.release()

    def _pump_council(self, topic: str, loop: asyncio.AbstractEventLoop) -> None:
        """Bridge the async council generator (on *loop*) to this thread as SSE.

        Carries prior rounds in so the advisors can follow up, and records this
        round into the shared history once it completes.
        """
        q: queue.Queue[Any] = queue.Queue()
        history = list(_council_history)  # snapshot for this run

        async def _produce() -> None:
            from novacode_cli.council import get_council_model, run_council

            try:
                model = get_council_model()
            except Exception as exc:  # noqa: BLE001
                q.put(("council_error", {"message": f"Model unavailable: {exc}"}))
                q.put(_STREAM_END)
                return

            try:
                async for event in run_council(topic, model, history=history):
                    etype = event.pop("type")
                    q.put((etype, event))
            except Exception as exc:  # noqa: BLE001
                q.put(("council_error", {"message": str(exc)}))
            finally:
                q.put(_STREAM_END)

        producer = asyncio.run_coroutine_threadsafe(_produce(), loop)

        # Accumulate this round from the event stream so we can append it to the
        # shared history once it completes cleanly.
        id_to_name: dict[str, str] = {}
        texts: dict[str, str] = {}
        order: list[str] = []
        winner_name: str | None = None
        completed = False

        while True:
            try:
                item = q.get(timeout=300)
            except queue.Empty:
                self._sse("council_error", {"message": "The council timed out"})
                producer.cancel()
                break

            if item is _STREAM_END:
                # Record the round before signalling done, so a follow-up request
                # (or a test) observing the terminal event sees it persisted.
                if completed and texts:
                    transcript = [[id_to_name.get(i, i), texts[i]] for i in order if i in texts]
                    _council_history.append(
                        {"topic": topic, "transcript": transcript, "winner": winner_name}
                    )
                self._sse("done", {})
                break

            etype, data = item
            if etype == "council_start":
                for a in data.get("agents", []):
                    id_to_name[a["id"]] = a["name"]
                    order.append(a["id"])
            elif etype == "agent_done":
                texts[data["id"]] = data.get("text", "")
            elif etype == "verdict":
                winner_name = data.get("winner_name")
                completed = True

            if not self._sse(etype, data):
                producer.cancel()  # client disconnected
                break

    def _sse(self, event: str, data: dict) -> bool:
        """Write one SSE frame. Returns False if the client has disconnected."""
        try:
            frame = f"event: {event}\ndata: {json.dumps(data)}\n\n"
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server that doesn't dump a traceback when a client disconnects.

    Browsers (and the SSE client) routinely drop the connection mid-stream — on
    ``done``, on navigation, or on reset — which surfaces as a connection error
    in the handler thread. That's expected, not a server fault, so we swallow it.
    """

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001, ARG002
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionError, OSError)):
            return
        logger.exception("Council server error handling %s", client_address)


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
    """Check if the council server is currently running."""
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
    """Store session references for the background HTTP server thread.

    The council itself only needs the event ``loop`` (to run model calls), but we
    keep the agent/session references for parity with the CLI/TUI call sites.
    """
    global _agent, _assistant_id, _session_state, _main_loop
    _agent = agent
    _assistant_id = assistant_id
    _session_state = session_state
    _main_loop = loop


def start_chat_server() -> str:
    """Start the HTTP council server in a daemon thread.

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

    _server = _QuietThreadingHTTPServer(("localhost", port), _ChatHandler)
    _server_thread = threading.Thread(
        target=_server.serve_forever, daemon=True, name="chat-http-server"
    )
    _server_thread.start()

    return f"http://localhost:{port}"


def stop_chat_server() -> bool:
    """Stop the running council server.

    Returns:
        True if the server was stopped, False if it wasn't running.
    """
    global _server, _server_thread, _server_port, _council_history

    if _server is None:
        return False

    _server.shutdown()
    _server.server_close()
    _server = None
    _server_thread = None
    _server_port = None
    _council_history = []
    return True


# ---------------------------------------------------------------------------
# CLI command handler
# ---------------------------------------------------------------------------

async def handle_chat_command() -> bool:
    """Handle the /chat command — start the council web UI (CLI entry point)."""
    if is_server_running():
        url = get_server_url()
        assert url is not None
        console.print()
        console.print(f"[green]Council UI already running at [bold]{url}[/bold][/green]")
        webbrowser.open(url)
        return True

    url = start_chat_server()
    console.print()
    console.print(f"[bold {COLORS['primary']}]== Nova Council ==[/bold {COLORS['primary']}]")
    console.print(f"[green]Council UI started at [bold]{url}[/bold][/green]")
    webbrowser.open(url)
    console.print("[dim]  Type /chat stop to stop the server.[/dim]")
    console.print()
    return True


async def handle_chat_stop_command() -> bool:
    """Handle the /chat stop command — stop the council web UI (CLI entry)."""
    if not is_server_running():
        console.print("[yellow]Council server is not running.[/yellow]")
        return True

    console.print("[dim]Shutting down council server...[/dim]")
    stop_chat_server()
    console.print("[green]Council server stopped.[/green]")
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
        return await handle_chat_command()

    registry.register("chat", _handle)
