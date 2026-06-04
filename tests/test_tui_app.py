"""Headless smoke test for the Phase-1 Textual TUI.

Boots ``NovaApp`` with a mocked agent via Textual's test pilot and verifies the
input -> worker -> run_agent_stream -> rendered-transcript loop runs without a
real terminal or API. Skipped if ``textual`` isn't installed.

Runnable directly (``python tests/test_tui_app.py``) or via pytest.
"""

from __future__ import annotations

import asyncio

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


class _Chunk:
    def __init__(self, mid, blocks):
        self.id = mid
        self._blocks = blocks
        self.usage_metadata = {"input_tokens": 20, "output_tokens": 8}

    @property
    def content_blocks(self):
        return self._blocks


class _StateVal:
    def __init__(self, msgs):
        self.values = {"messages": msgs}


class _FakeAgent:
    async def aget_state(self, config):
        return _StateVal([])

    async def astream(self, inp, **kw):
        yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "Hi from Nova"}]), {}))
        yield (
            (),
            "messages",
            (
                _Chunk(
                    "m2",
                    [
                        {
                            "type": "tool_call_chunk",
                            "name": "shell",
                            "id": "t1",
                            "args": {"command": "ls"},
                            "index": 0,
                        }
                    ],
                ),
                {},
            ),
        )

    async def aupdate_state(self, **kw):
        pass


class _SS:
    thread_id = "t1"
    auto_approve = True
    plan_mode_enabled = False
    todos: list = []


async def _drive():
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    tt = TokenTracker()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=tt,
        image_tracker=None,
        model_name="test-model",
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt")
        inp.value = "hello"
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.query_one("#transcript").children) > 0


async def _drive_routing():
    """Exercise input routing: slash commands, !bash, normal prompt, /clear."""
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _SSNoDecomp(_SS):
        prompt_decomposition_enabled = False

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SSNoDecomp(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )

    async def submit(pilot, text):
        inp = app.query_one("#prompt")
        inp.value = text
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        tr = app.query_one("#transcript")
        await submit(pilot, "/help")
        assert len(tr.children) > 0
        await submit(pilot, "hello there")  # -> agent
        await submit(pilot, "!echo hi")  # -> bash
        await submit(pilot, "/tokens")
        before = len(tr.children)
        await submit(pilot, "/clear")
        assert len(tr.children) < before
        await submit(pilot, "/bogus")  # unknown -> notice, no crash


async def _drive_save_on_quit():
    """/quit should persist the session via the session manager."""
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _Msg:
        def __init__(self, i):
            self.id = i

    class _StateWithMsgs:
        def __init__(self):
            self.values = {"messages": [_Msg("a"), _Msg("b")], "todos": []}

    class _AgentWithState(_FakeAgent):
        async def aget_state(self, config):
            return _StateWithMsgs()

    class _SSId(_SS):
        session_id = "s1"

    saved = {}

    class _FakeSM:
        def save_session(self, **kw):
            saved.update(kw)

    app = NovaApp(
        agent=_AgentWithState(),
        assistant_id="nova-agent",
        session_state=_SSId(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=_FakeSM(),
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt")
        inp.value = "/quit"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
    assert saved.get("session_id") == "s1", saved
    assert len(saved.get("messages", [])) == 2, saved


def test_tui_headless_run():
    if not _HAS_TEXTUAL:
        return  # textual not installed in this environment — skip
    asyncio.run(_drive())


async def _drive_sessions_screen():
    """/sessions opens a screen listing saved sessions."""
    from textual.widgets import Button, OptionList

    from novacode_cli.tui.app import NovaApp, SessionsScreen
    from novacode_cli.ui.ui_elements import TokenTracker

    class _Meta:
        def __init__(self, sid):
            self.session_id = sid
            self.last_active = "2026-06-01T00:00:00+00:00"
            self.project_root = None
            self.model_name = "m"
            self.message_count = 3

    class _SM:
        def list_sessions(self, limit=20):
            return [_Meta("cur12345"), _Meta("old99999")]

        def delete_session(self, sid):
            return True

    class _SSId(_SS):
        session_id = "cur12345"

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SSId(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=_SM(),
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt")
        inp.value = "/sessions"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen), type(app.screen).__name__
        assert app.screen.query_one("#sessions", OptionList).option_count == 2
        app.screen.query_one("#close", Button).press()
        await pilot.pause()


def test_tui_saves_on_quit():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_save_on_quit())


async def _drive_mcp_screen():
    """/mcp opens a screen (lists configured servers or a placeholder)."""
    from textual.widgets import Button, OptionList

    from novacode_cli.tui.app import McpScreen, NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt")
        inp.value = "/mcp"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, McpScreen), type(app.screen).__name__
        # >=1: real servers, or the "(no MCP servers configured)" placeholder.
        assert app.screen.query_one("#mcp-configured", OptionList).option_count >= 1
        app.screen.query_one("#close", Button).press()
        await pilot.pause()


def test_tui_sessions_screen():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_sessions_screen())


async def _drive_autocomplete():
    """Typing '/mo' shows a filtered command palette; Enter accepts '/model '."""
    from textual.widgets import Input, OptionList

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        app.query_one("#prompt", Input).focus()
        pal = app.query_one("#cmdpalette", OptionList)
        await pilot.press("/")
        await pilot.press("m")
        await pilot.press("o")
        await pilot.pause()
        assert pal.display and pal.option_count >= 1
        opts = [str(pal.get_option_at_index(i).prompt) for i in range(pal.option_count)]
        assert "/model" in opts, opts
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#prompt", Input).value.strip() == "/model"
        assert not pal.display


async def _drive_agents_skills():
    """/agents and /skills open read-only list screens."""
    from textual.widgets import Button, Input

    from novacode_cli.tui.app import InfoListScreen, NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        for cmd in ("/agents", "/skills"):
            inp = app.query_one("#prompt", Input)
            inp.value = cmd
            inp.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, InfoListScreen), (cmd, type(app.screen).__name__)
            app.screen.query_one("#close", Button).press()
            await pilot.pause()


def test_tui_mcp_screen():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_mcp_screen())


def test_tui_autocomplete():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_autocomplete())


async def _drive_skill_agent_autocomplete():
    """'/skill:' lists skills and '@' lists agents in the palette."""
    from textual.widgets import Input, OptionList

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    app._skill_names_cache = ["api-testing", "code-review", "graphify"]
    app._agent_names_cache = ["researcher", "critic"]
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt", Input)
        inp.focus()
        pal = app.query_one("#cmdpalette", OptionList)

        inp.value = "/skill:"
        await pilot.pause()
        skills = [str(pal.get_option_at_index(i).prompt) for i in range(pal.option_count)]
        assert pal.display and "/skill:api-testing" in skills, skills

        inp.value = "/skill:co"
        await pilot.pause()
        assert [
            str(pal.get_option_at_index(i).prompt) for i in range(pal.option_count)
        ] == ["/skill:code-review"]

        inp.value = "@"
        await pilot.pause()
        agents = [str(pal.get_option_at_index(i).prompt) for i in range(pal.option_count)]
        assert pal.display and "@researcher" in agents and "@critic" in agents, agents

        inp.value = "@cr"
        await pilot.pause()
        assert [
            str(pal.get_option_at_index(i).prompt) for i in range(pal.option_count)
        ] == ["@critic"]


def test_tui_agents_skills_screens():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_agents_skills())


async def _drive_remote_render():
    """A remote message renders in the transcript and is replied to."""
    from langchain_core.messages import AIMessage

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _StateMsgs:
        def __init__(self, msgs):
            self.values = {"messages": msgs, "todos": []}

    class _AgentRecording:
        def __init__(self):
            self._msgs = []

        async def aget_state(self, config):
            return _StateMsgs(list(self._msgs))

        async def astream(self, inp, **kw):
            yield ((), "messages", (_Chunk("r1", [{"type": "text", "text": "Reply!"}]), {}))
            self._msgs.append(AIMessage(content="Reply!", id="r1"))

        async def aupdate_state(self, **kw):
            pass

    replies = []

    class _Platform:
        value = "discord"

    class _RemoteMsg:
        text = "hi from discord"
        user_name = "alice"
        platform = _Platform()
        typing_fn = None

        async def reply_fn(self, t):
            replies.append(t)

    class _SSRemote:
        thread_id = "t1"
        session_id = "s1"
        auto_approve = False
        plan_mode_enabled = False
        todos: list = []

        def __init__(self):
            self._remote_message_queue = asyncio.Queue()
            self._remote_message_lock = asyncio.Lock()
            self._remote_bridge_manager = None

    ss = _SSRemote()
    app = NovaApp(
        agent=_AgentRecording(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await ss._remote_message_queue.put(_RemoteMsg())
        for _ in range(30):
            await pilot.pause()
            if replies:
                break
        assert replies and "Reply!" in replies[0], replies
        assert len(app.query_one("#transcript").children) > 0
        assert ss.auto_approve is False  # restored after the remote turn


def test_tui_skill_agent_autocomplete():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_skill_agent_autocomplete())


async def _drive_live_render():
    """Reasoning + answer stream into ChatMessage widgets; tool sets status; commit clears."""
    import novacode_cli.ui_events as ev

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await app._render(ev.ReasoningDelta("thinking hard"))
        assert app._reason_msg is not None
        assert "thinking hard" in app._reasoning_buf
        assert len(app.query("ChatMessage.reason")) == 1
        await app._render(ev.ToolCall(name="shell", display_str="shell(ls)", icon="+"))
        assert app._activity == "running shell…", app._activity
        assert app._last_tool is not None
        # tool result fills the collapsible body and clears the ref
        await app._render(
            ev.ToolResult(preview="1 result", is_error=False, full_output="line1\nline2")
        )
        assert app._last_tool is None
        assert len(app.query("Collapsible.tool")) == 1
        await app._render(ev.TextDelta("hi"))
        assert app._activity == "responding…"
        assert app._stream_msg is not None and app._live_buf == "hi"
        await app._render(
            ev.AssistantMessage(text="done", agent_name="Nova", agent_color="cyan")
        )
        assert app._stream_msg is None and app._live_buf == ""
        assert app._reason_msg is None
        assert len(app.query("ChatMessage.nova")) >= 1


def test_tui_remote_render():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_remote_render())


async def _drive_markup_safe():
    """Tool titles + question options containing '[' must not crash markup render."""
    import novacode_cli.ui_events as ev

    from novacode_cli.tui.app import NovaApp, QuestionModal
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        # Brackets in args/preview previously raised "Expected markup value".
        await app._render(
            ev.ToolCall(
                name="shell", display_str="grep('[abc]?)')", icon="+", call_id="c1"
            )
        )
        await app._render(
            ev.ToolResult(
                preview="found [1] ?)", is_error=False, full_output="x", call_id="c1"
            )
        )
        assert len(app.query("Collapsible.tool")) == 1

        # QuestionModal with bracketed question/options must render cleanly.
        await app.push_screen(
            QuestionModal(
                {"question": "pick [a] or [b]?", "options": ["use [x]", "use [y]"]}
            )
        )
        await pilot.pause()
        assert isinstance(app.screen, QuestionModal), type(app.screen).__name__
        app.pop_screen()
        await pilot.pause()


def test_tui_markup_safe():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_markup_safe())


async def _drive_context_warning():
    """_check_context warns once at the warning line and re-arms below it."""
    from textual.widgets import Static

    from novacode_cli.tui.app import NovaApp

    class _BD:
        def __init__(self, pct, warn, crit):
            self.usage_percentage = pct
            self.is_warning = warn
            self.is_critical = crit

    class _TT:
        def __init__(self):
            self._bd = None

        def get_breakdown(self):
            return self._bd

    tt = _TT()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=tt,
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )
    app._auto_compact = False  # don't invoke the model in the test
    async with app.run_test() as pilot:
        tt._bd = _BD(80.0, True, False)
        await app._check_context()
        assert app._ctx_warned is True
        # Critical (no auto-compact) -> strong warning logged.
        tt._bd = _BD(96.0, True, True)
        await app._check_context()
        await pilot.pause()
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "critical" in txt.lower(), txt
        # Back below the warning line -> re-arm so the next rise warns again.
        tt._bd = _BD(40.0, False, False)
        await app._check_context()
        assert app._ctx_warned is False


def test_tui_context_warning():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_context_warning())


async def _drive_live_steering():
    """Typing while the agent works injects a transient steer, cleared after."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    ss = _SS()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )
    async with app.run_test() as pilot:
        app._turn_active = True  # simulate an in-flight turn
        inp = app.query_one("#prompt", Input)
        inp.value = "focus on error handling"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        # Injected as a steering instruction (not dispatched as a new turn).
        instrs = ss.steering_instructions
        assert any(si.instruction == "focus on error handling" for si in instrs), instrs
        assert len(app._live_steers) == 1
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "Steering" in txt, txt
        # Turn-end cleanup removes the transient steer (one-turn lifetime).
        app._turn_active = False
        app._clear_live_steers()
        assert len(app._live_steers) == 0
        assert not any(
            si.instruction == "focus on error handling" for si in ss.steering_instructions
        )


def test_tui_live_steering():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_live_steering())


async def _drive_stream_coalescing():
    """A burst of TextDeltas schedules exactly ONE coalesced flush; the buffer is
    intact and _flush_stream paints it; AssistantMessage finalizes + cancels."""
    import novacode_cli.ui_events as ev
    from textual.widgets import Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        # Stub set_timer so the coalesced flush never auto-fires — we drive it.
        timer_calls = {"n": 0}
        app.set_timer = lambda delay, fn, *a, **k: timer_calls.__setitem__(
            "n", timer_calls["n"] + 1
        )
        for part in ("Hel", "lo ", "wor", "ld"):
            await app._render(ev.TextDelta(part))
        # Widget mounted once; the 4 deltas coalesced into a single scheduled flush.
        assert app._stream_msg is not None
        assert app._live_buf == "Hello world"
        assert app._stream_flush_scheduled is True
        assert timer_calls["n"] == 1, timer_calls
        # The repaint reflects the full buffer and clears the pending flag.
        app._flush_stream()
        assert app._stream_flush_scheduled is False
        body = app._stream_msg.query_one(".body", Static)
        assert "Hello world" in str(body.render())
        # Finalize: markdown commit clears buffers and cancels any pending flush.
        await app._render(
            ev.AssistantMessage(text="Hello world", agent_name="Nova", agent_color="cyan")
        )
        assert app._stream_msg is None and app._live_buf == ""
        assert app._stream_flush_scheduled is False


def test_tui_stream_coalescing():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_stream_coalescing())


async def _drive_transcript_cap():
    """The transcript is pruned from the top past the cap; tracked in-progress
    widgets survive even when they're the oldest."""
    from textual.widgets import Static

    import novacode_cli.tui.app as appmod
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    hi, lo = appmod._MAX_TRANSCRIPT_WIDGETS, appmod._TRANSCRIPT_LOW_WATER
    appmod._MAX_TRANSCRIPT_WIDGETS = 10
    appmod._TRANSCRIPT_LOW_WATER = 6
    try:
        app = NovaApp(
            agent=_FakeAgent(),
            assistant_id="nova-agent",
            session_state=_SS(),
            backend=None,
            token_tracker=TokenTracker(),
            image_tracker=None,
            model_name="m",
        )
        async with app.run_test() as pilot:
            # Mark an (old) widget as in-progress so pruning must spare it.
            protected = Static("PROTECTED")
            await app._mount(protected)
            app._init_widget = protected
            for i in range(30):
                await app._mount(Static(f"line {i}"))
            tr = app._transcript()
            assert len(tr.children) <= appmod._MAX_TRANSCRIPT_WIDGETS, len(tr.children)
            assert protected in tr.children  # tracked widget survived pruning
    finally:
        appmod._MAX_TRANSCRIPT_WIDGETS = hi
        appmod._TRANSCRIPT_LOW_WATER = lo


def test_tui_transcript_cap():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_transcript_cap())


async def _drive_palette_noop():
    """_update_palette doesn't rebuild the OptionList when candidates are
    unchanged; on_key bails fast when the palette is hidden."""
    from textual.widgets import OptionList

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        palette = app._w("#cmdpalette", OptionList)
        rebuilds = {"n": 0}
        _orig_clear = palette.clear_options

        def _counting_clear(*a, **k):
            rebuilds["n"] += 1
            return _orig_clear(*a, **k)

        palette.clear_options = _counting_clear

        app._update_palette("/h")  # matches /help, /hooks, … → builds once
        assert app._last_palette and all(
            c.startswith("/h") for c in app._last_palette
        )
        assert rebuilds["n"] == 1
        first_list = list(app._last_palette)
        app._update_palette("/h")  # identical input → candidates unchanged
        assert rebuilds["n"] == 1, "palette rebuilt despite unchanged candidates"
        assert app._last_palette == first_list

        # on_key is a no-op (no exception) when the palette is hidden.
        app._hide_palette()

        class _K:
            key = "down"

            def stop(self):
                pass

            def prevent_default(self):
                pass

        assert app.on_key(_K()) is None


def test_tui_palette_noop():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_palette_noop())


async def _drive_startup_info():
    """The native startup panel renders model/cwd on mount."""
    from textual.widgets import Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="deepseek-v4",
        session_manager=None,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        blob = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "session" in blob and "deepseek-v4" in blob, blob


def test_tui_startup_info():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_startup_info())


def test_plan_agent_shares_steering_list(monkeypatch):
    """The plan agent's SteeringMiddleware holds the SAME list as the session,
    even when it starts empty (regression for the `or []` reference bug)."""
    import deepagents.graph as dg
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from novacode_cli.agents.plan_agent import create_plan_agent_with_config

    captured: dict = {}

    def _fake_create_deep_agent(**kw):
        captured["middleware"] = kw.get("middleware")
        return object()  # the factory wraps this as (agent, backend)

    monkeypatch.setattr(dg, "create_deep_agent", _fake_create_deep_agent)

    shared: list = []  # empty on purpose — the bug swapped this for a fresh []
    create_plan_agent_with_config(
        model=FakeListChatModel(responses=["x"]),
        assistant_id="nova",
        tools=[],
        steering_instructions=shared,
    )
    mws = captured["middleware"] or []
    steer = next(m for m in mws if type(m).__name__ == "SteeringMiddleware")
    # Must be the SAME object, so live appends are visible to the plan agent.
    assert steer._instructions is shared


async def _drive_approval():
    """Rich approval modal: 'a' auto-approves and sets the session flag."""
    import novacode_cli.ui_events as ev

    from novacode_cli.tui.app import ApprovalModal, NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _SSManual(_SS):
        auto_approve = False
        plan_mode_enabled = False

    ss = _SSManual()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        fut = asyncio.get_event_loop().create_future()
        req = ev.InterruptRequest(
            kind="tool",
            payload={"action_requests": [{"name": "shell", "args": {"command": "ls"}}]},
            future=fut,
        )
        app.run_worker(app._handle_interrupt(req))
        await pilot.pause()
        assert isinstance(app.screen, ApprovalModal), type(app.screen).__name__
        # Choices must be present and reachable (regression: a long body used to
        # push the OptionList off-screen, leaving only Enter usable).
        from textual.widgets import OptionList

        choices = app.screen.query_one("#choices", OptionList)
        assert choices.option_count >= 2, choices.option_count
        assert app.screen.query("#modal-body-scroll"), "body must be in a scroll region"
        await pilot.press("a")  # auto-approve for this session
        res = await asyncio.wait_for(fut, 2)
        assert res["decisions"][0]["type"] == "approve", res
        assert ss.auto_approve is True


def test_tui_live_render():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_live_render())


async def _drive_parallel_fileops():
    """Parallel read_file calls each finalize their OWN tool component via call_id."""
    import novacode_cli.ui_events as ev

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await app._render(
            ev.ToolCall(name="read_file", display_str="read_file(a.py)", icon="+", call_id="c1")
        )
        await app._render(
            ev.ToolCall(name="read_file", display_str="read_file(b.py)", icon="+", call_id="c2")
        )
        assert len(app._tool_components) == 2
        # results arrive as FileOp events (file-op tools) — finalize each by id
        await app._render(ev.FileOp(record=None, full_output="content-A", call_id="c1"))
        await app._render(ev.FileOp(record=None, full_output="content-B", call_id="c2"))
        assert len(app._tool_components) == 0
        comps = list(app.query("Collapsible.tool"))
        assert len(comps) == 2, len(comps)
        # both finalized (title shows ✓, not the stuck "running…")
        assert all("✓" in str(c.title) and "running" not in str(c.title) for c in comps)


def test_tui_approval_modal():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_approval())


async def _drive_diff_component():
    """An edit_file FileOp renders its diff into the component (no stray block)."""
    import novacode_cli.ui_events as ev

    from novacode_cli.file_ops import FileOperationRecord, FileOpMetrics
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    rec = FileOperationRecord(
        tool_name="edit_file",
        display_path="/workspace/joji.md",
        physical_path=None,
        tool_call_id="c1",
        status="success",
        metrics=FileOpMetrics(lines_added=96, lines_removed=0),
        diff="--- a\n+++ b\n@@ -0,0 +1 @@\n+# Joji\n",
    )
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await app._render(
            ev.ToolCall(
                name="edit_file",
                display_str="edit_file(/workspace/joji.md)",
                icon="+",
                call_id="c1",
            )
        )
        await app._render(ev.FileOp(record=rec, full_output="", call_id="c1"))
        comps = list(app.query("Collapsible.tool"))
        assert len(comps) == 1
        title = str(comps[0].title)
        assert "+96 / -0" in title and "✓" in title and "running" not in title, title
        assert len(app._tool_components) == 0


def test_tui_parallel_fileops():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_parallel_fileops())


async def _drive_remote_screen():
    """/remote opens a native screen rendering bridge status as TUI components."""
    from textual.widgets import Button, Static

    from novacode_cli.tui.app import NovaApp, RemoteScreen
    from novacode_cli.ui.ui_elements import TokenTracker

    class _Mgr:
        active_bridges: list = []

    class _SSRemote(_SS):
        def __init__(self):
            self._remote_bridge_manager = _Mgr()
            self._remote_message_queue = None

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SSRemote(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt")
        inp.value = "/remote"
        inp.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, RemoteScreen), type(app.screen).__name__
        status = str(app.screen.query_one("#remote-status", Static).render())
        assert "No bridges active" in status, status
        assert app.screen.query_one("#start-discord", Button)
        app.screen.query_one("#close", Button).press()
        await pilot.pause()


def test_tui_diff_component():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_diff_component())


async def _drive_native_todos():
    """Todos render natively and update a single widget in place (no pile-up)."""
    import novacode_cli.ui_events as ev

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await app._render(
            ev.TodoUpdate(
                todos=[
                    {"content": "x", "status": "completed"},
                    {"content": "y", "status": "in_progress"},
                ],
                agent_name=None,
            )
        )
        assert app._todo_widget is not None
        assert len(app.query(".todos")) == 1
        # a second update reuses the same widget
        await app._render(
            ev.TodoUpdate(todos=[{"content": "x", "status": "completed"}], agent_name=None)
        )
        assert len(app.query(".todos")) == 1


def test_tui_remote_screen():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_remote_screen())


async def _drive_init_routes_native():
    """/init routes to the native handler (not the 'unavailable' fallback)."""
    import novacode_cli.config.config as cfg
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        prev_root = cfg.settings.project_root
        cfg.settings.project_root = None  # deterministic no-project path
        try:
            inp = app.query_one("#prompt")
            inp.value = "/init"
            inp.focus()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
        finally:
            cfg.settings.project_root = prev_root
        # native notice rendered; not the "isn't available in --tui" fallback
        from textual.widgets import Static

        texts = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in texts, texts
        assert "requires a project" in texts or "Initializing NOVA.md" in texts, texts


def test_tui_native_todos():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_native_todos())


async def _drive_init_live_stream():
    """The /init pipeline drives a NATIVE step tracker via structured events
    (StepStarted/StepDetail → _init_on_event), not captured console text."""
    from textual.widgets import Static

    from novacode_cli.init import events as iev
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        app._init_steps = [
            {"label": n, "status": "pending", "detail": ""}
            for n in (
                "Detect files",
                "Extract entities",
                "Build & cluster graph",
                "Analyze structure",
                "Generate docs",
            )
        ]
        app._init_widget = Static("", classes="initlog")
        await app.query_one("#transcript").mount(app._init_widget)
        app._init_render_steps()
        app._init_on_event(iev.StepStarted(1, 5, "Detecting project files"))
        app._init_on_event(iev.StepDetail("34 files · 1,000 words"))
        app._init_on_event(iev.StepStarted(3, 5, "Building knowledge graph"))
        app._init_finish()
        await pilot.pause()
        rendered = str(app._init_widget.render())
        # native tracker keeps the concise pre-set labels; the emitted detail and
        # completion glyphs are shown (no verbatim "Step N/5" parsing).
        assert "Detect files" in rendered, rendered
        assert "34 files" in rendered and "✓" in rendered, rendered


async def _drive_native_diff_body():
    """FileOp renders a NATIVE colored diff in the component body (no legacy capture)."""
    import novacode_cli.ui_events as ev
    from textual.widgets import Static

    from novacode_cli.file_ops import FileOperationRecord, FileOpMetrics
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    rec = FileOperationRecord(
        tool_name="edit_file",
        display_path="/x/joji.md",
        physical_path=None,
        tool_call_id="c1",
        status="success",
        metrics=FileOpMetrics(lines_added=2, lines_removed=1),
        diff="--- a\n+++ b\n@@ -1 +1,2 @@\n-old line\n+# Joji\n+Singer\n",
    )
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        await app._render(
            ev.ToolCall(
                name="edit_file",
                display_str="edit_file(/x/joji.md)",
                icon="+",
                call_id="c1",
            )
        )
        await app._render(ev.FileOp(record=rec, full_output="", call_id="c1"))
        comp = app.query("Collapsible.tool").first()
        body = str(comp.query_one(".toolbody", Static).render())
        assert "+# Joji" in body and "-old line" in body, body
        assert "+2 / -1" in str(comp.title)


async def _drive_native_bash():
    """! commands run natively (subprocess) and render output as TUI loglines."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt", Input)
        inp.value = "!echo hi-from-shell"
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        texts = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        # the command line (and, on most shells, its echoed output) appears
        assert "hi-from-shell" in texts, texts


def test_tui_native_diff_body():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_native_diff_body())


def test_tui_native_bash():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_native_bash())


def test_tui_init_routes_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_init_routes_native())


async def _drive_trace_log_plan_native():
    """/trace, /log, /plan render natively (not the 'unavailable' fallback)."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _SSPlan(_SS):
        plan_agent = None
        plan_backend = None

        def clear_plan_agent(self):
            self.plan_agent = None

    ss = _SSPlan()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "/trace")
        await submit(pilot, "/trace disable")  # native, no passthrough
        await submit(pilot, "/trace help")
        await submit(pilot, "/log")
        await submit(pilot, "/log grep nonexistent_pattern_xyz")  # native grep
        await submit(pilot, "/plan status")
        await submit(pilot, "/plan off")
        assert ss.plan_mode_enabled is False
        # plan-mode routing helper falls back to the main agent when off
        ag, _ = app._active_agent()
        assert ag is app.agent
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in txt, txt


def test_tui_init_live_stream():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_init_live_stream())


async def _drive_steer_save_native():
    """/steer (add/list/clear) and /save render natively (no fallback)."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _SSSteer(_SS):
        steering_instructions = None

    ss = _SSSteer()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "/steer always use type hints")
        assert ss.steering_instructions and len(ss.steering_instructions) == 1
        await submit(pilot, "/steer clear")
        assert len(ss.steering_instructions) == 0
        await submit(pilot, "/save")  # no session_manager -> native notice
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in txt, txt


async def _drive_research_dream_native():
    """/research streams natively via execute_fn; /dream renders natively."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "/research quick how do async generators work")
        await submit(pilot, "/dream")
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in txt, txt
        # research header surfaced natively
        assert "Research" in txt, txt


def test_tui_research_dream_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_research_dream_native())


async def _drive_images_native():
    """/images list/remove/clear render natively against a fake tracker."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _FakeTracker:
        def __init__(self):
            self._imgs = [
                {
                    "id": "image-1",
                    "format": "png",
                    "size_kb": 12.5,
                    "placeholder": "[image-1]",
                }
            ]

        @property
        def count(self):
            return len(self._imgs)

        def list_images(self):
            return list(self._imgs)

        def remove_image(self, image_id):
            before = len(self._imgs)
            self._imgs = [i for i in self._imgs if i["id"] != image_id]
            return len(self._imgs) < before

        def clear(self):
            self._imgs = []

    tracker = _FakeTracker()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=tracker,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "/images")
        await submit(pilot, "/images remove 1")
        assert tracker.count == 0
        await submit(pilot, "/images")  # now empty
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in txt, txt
        assert "image-1" in txt, txt


def test_tui_images_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_images_native())


async def _drive_menus_native():
    """/files, /hooks, /kill, /restore render natively (empty-state, no modal)."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "/files")
        await submit(pilot, "/hooks list")
        await submit(pilot, "/restore")  # no recovery manager -> native notice
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "isn't available" not in txt, txt
        assert "Session file operations" in txt, txt


def test_tui_menus_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_menus_native())


async def _drive_input_mode_styles():
    """The prompt input gets distinct CSS classes for bash vs plan mode."""
    from textual.widgets import Input

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    class _SSPlanFlag(_SS):
        plan_mode_enabled = False

    ss = _SSPlanFlag()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", Input)

        # Bash mode: typing "!" flips on bash-mode (not plan-mode).
        app._update_mode_badge("!ls -la")
        assert prompt.has_class("bash-mode"), "expected bash-mode class"
        assert not prompt.has_class("plan-mode")
        assert app._input_pulse_mode == "bash"

        # Plan mode (no bash): plan-mode class, calm pulse.
        ss.plan_mode_enabled = True
        app._update_mode_badge("")
        assert prompt.has_class("plan-mode"), "expected plan-mode class"
        assert not prompt.has_class("bash-mode")
        assert app._input_pulse_mode == "plan"

        # Plan + bash typed together: bash wins the input styling.
        app._update_mode_badge("!echo hi")
        assert prompt.has_class("bash-mode")
        assert not prompt.has_class("plan-mode")

        # Back to normal: both classes cleared, pulse stopped.
        ss.plan_mode_enabled = False
        app._update_mode_badge("")
        assert not prompt.has_class("bash-mode")
        assert not prompt.has_class("plan-mode")
        assert app._input_pulse_mode is None


def test_tui_input_mode_styles():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_input_mode_styles())


async def _drive_theme_native():
    """/theme lists themes (incl. registered tokyo-night) and switching applies."""
    import novacode_cli.config.nova_config as ncfg
    from textual.widgets import Button, Input, OptionList

    from novacode_cli.tui.app import NovaApp, ThemeScreen
    from novacode_cli.ui.ui_elements import TokenTracker

    # Don't write the user's real config during the test.
    _orig_set = ncfg.NovaConfig.set
    ncfg.NovaConfig.set = lambda self, k, v: None
    try:
        app = NovaApp(
            agent=_FakeAgent(),
            assistant_id="nova-agent",
            session_state=_SS(),
            backend=None,
            token_tracker=TokenTracker(),
            image_tracker=None,
            model_name="m",
            session_manager=None,
        )
        async with app.run_test() as pilot:
            # Nova's palette is registered as a real theme.
            assert "tokyo-night" in app.available_themes

            inp = app.query_one("#prompt", Input)
            inp.value = "/theme"
            inp.focus()
            await pilot.press("enter")
            # /theme pushes a modal via push_screen_wait, which blocks the
            # dispatch worker until dismissed — do NOT wait_for_complete here
            # (that would deadlock); just pump until the screen appears.
            for _ in range(10):
                await pilot.pause()
                if isinstance(app.screen, ThemeScreen):
                    break

            assert isinstance(app.screen, ThemeScreen), type(app.screen).__name__
            scr = app.screen
            assert "tokyo-night" in scr._theme_names
            assert len(scr._theme_names) > 1

            # Switch to a different theme and confirm it actually applies.
            current = app.theme
            target = next(n for n in scr._theme_names if n != current)
            ol = scr.query_one("#theme-list", OptionList)
            ol.highlighted = scr._theme_names.index(target)
            scr._do_apply()
            await pilot.pause()
            assert app.theme == target, app.theme

            # Dismiss the modal so the dispatch worker can finish.
            scr.query_one("#close", Button).press()
            await pilot.pause()
    finally:
        ncfg.NovaConfig.set = _orig_set


def test_tui_theme_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_theme_native())


async def _drive_notifications_native():
    """Notifications show a status badge and /notifications lists/dismisses them."""
    from textual.widgets import Input, Static

    from novacode_cli.states.Session import SessionState
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    ss = SessionState()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        # Raising a notification surfaces a 🔔 badge in the status bar.
        ss.add_notification("success", "Build done", "ok", "tests")
        app._refresh_status()
        await pilot.pause()
        status_txt = str(app.query_one("#status", Static).render())
        assert "🔔" in status_txt, status_txt

        # /notifications lists it natively.
        await submit(pilot, "/notifications")
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "Build done" in txt, txt
        assert "isn't available" not in txt, txt

        # Dismissing clears the unread count (and the badge).
        nid = ss.notifications[0].id
        await submit(pilot, f"/notifications dismiss {nid}")
        assert ss.unread_notification_count() == 0
        app._refresh_status()
        await pilot.pause()
        assert "🔔" not in str(app.query_one("#status", Static).render())


def test_tui_notifications_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_notifications_native())


async def _drive_resume_replay():
    """Restored messages are replayed into the transcript on resume."""
    from langchain_core.messages import AIMessage, HumanMessage
    from textual.widgets import Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    msgs = [
        HumanMessage(content="hello there nova"),
        AIMessage(content="hi — how can I help?"),
    ]
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=_SS(),
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
        restored_messages=msgs,
    )
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        # Both prior turns are replayed as ChatMessage cards (user + nova),
        from novacode_cli.tui.app import ChatMessage

        users = app.query("ChatMessage.user")
        novas = app.query("ChatMessage.nova")
        assert len(users) >= 1, f"no user message replayed ({len(users)})"
        assert len(novas) >= 1, f"no nova message replayed ({len(novas)})"
        # and a "resumed" notice records how many were restored.
        blob = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "Resumed" in blob and "2" in blob, blob


def test_tui_resume_replay():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_resume_replay())


async def _drive_clear_resets_chat():
    """/clear starts a fresh chat: new thread_id, cleared seen-ids + transcript."""
    from textual.widgets import Input, Static

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    ss = _SS()
    ss.thread_id = "orig-thread"
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=None,
        model_name="m",
        session_manager=None,
    )

    async def submit(pilot, t):
        inp = app.query_one("#prompt", Input)
        inp.value = t
        inp.focus()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    async with app.run_test() as pilot:
        await submit(pilot, "hello there")  # build some history
        app._seen.add("sentinel")
        await submit(pilot, "/clear")
        # New conversation thread + cleared per-chat tracking.
        assert ss.thread_id != "orig-thread", ss.thread_id
        assert "sentinel" not in app._seen
        txt = " ".join(
            str(w.render()) for w in app.query("#transcript .logline").results(Static)
        )
        assert "new chat" in txt.lower(), txt


def test_tui_clear_resets_chat():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_clear_resets_chat())


def test_tui_trace_log_plan_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_trace_log_plan_native())


def test_tui_steer_save_native():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_steer_save_native())


def test_tui_input_routing():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_routing())


if __name__ == "__main__":
    if _HAS_TEXTUAL:
        asyncio.run(_drive())
        asyncio.run(_drive_routing())
        asyncio.run(_drive_save_on_quit())
        asyncio.run(_drive_sessions_screen())
        asyncio.run(_drive_mcp_screen())
        asyncio.run(_drive_autocomplete())
        asyncio.run(_drive_agents_skills())
        asyncio.run(_drive_skill_agent_autocomplete())
        asyncio.run(_drive_remote_render())
        asyncio.run(_drive_live_render())
        asyncio.run(_drive_approval())
        asyncio.run(_drive_parallel_fileops())
        asyncio.run(_drive_diff_component())
        asyncio.run(_drive_remote_screen())
        asyncio.run(_drive_native_todos())
        asyncio.run(_drive_init_routes_native())
        asyncio.run(_drive_init_live_stream())
        asyncio.run(_drive_trace_log_plan_native())
        asyncio.run(_drive_native_diff_body())
        asyncio.run(_drive_native_bash())
        asyncio.run(_drive_steer_save_native())
        asyncio.run(_drive_research_dream_native())
        asyncio.run(_drive_images_native())
        asyncio.run(_drive_menus_native())
        asyncio.run(_drive_input_mode_styles())
        asyncio.run(_drive_theme_native())
        asyncio.run(_drive_notifications_native())
        asyncio.run(_drive_resume_replay())
        asyncio.run(_drive_clear_resets_chat())
        asyncio.run(_drive_markup_safe())
        asyncio.run(_drive_context_warning())
        asyncio.run(_drive_live_steering())
        asyncio.run(_drive_startup_info())
        print(
            "TUI HEADLESS + ROUTING + SAVE + SESSIONS + MCP + AUTOCOMPLETE + "
            "AGENTS/SKILLS + SKILL/@ + REMOTE + LIVE + APPROVAL + FILEOPS + DIFF + "
            "REMOTE-SCREEN + TODOS + INIT + INIT-STREAM + TRACE/LOG/PLAN + "
            "NATIVE-DIFF + BASH + RESEARCH/DREAM + IMAGES + MENUS + MODE-STYLES + "
            "THEME + NOTIFICATIONS + RESUME-REPLAY + CLEAR + MARKUP-SAFE + CONTEXT + "
            "LIVE-STEER OK"
        )
    else:
        print("textual not installed — skipped")
