"""Plan-scoped auto-approve must reset after the plan run."""
import asyncio
from types import SimpleNamespace

from novacode_cli.tui.app import NovaApp


def _stub(approved_plan, auto_approve=True, scoped=True):
    logs = []
    ran = []

    class _SS(SimpleNamespace):
        def consume_approved_plan(self):
            return approved_plan
        def clear_plan_agent(self):
            pass
        def reset_conversation(self):
            pass

    stub = SimpleNamespace(
        session_state=_SS(auto_approve=auto_approve),
        _plan_scoped_auto_approve=scoped,
        _log=lambda *a, **k: logs.append(a),
    )
    async def _sp(text):
        ran.append(text)
    stub._stream_prompt = _sp
    async def _noop_remove():
        return None

    stub._transcript = lambda: SimpleNamespace(remove_children=lambda: _noop_remove())
    stub._show_home_banner = lambda: None
    return stub, ran


def test_auto_approve_restored_after_plan_run():
    stub, ran = _stub("# My Plan\n1. do thing")
    asyncio.run(NovaApp._maybe_run_approved_plan(stub))
    assert ran, "plan should have executed"
    assert stub.session_state.auto_approve is False, "auto_approve must reset after plan run"
    assert stub._plan_scoped_auto_approve is False


def test_auto_approve_restored_even_without_plan_content():
    stub, ran = _stub(None)
    asyncio.run(NovaApp._maybe_run_approved_plan(stub))
    assert not ran
    assert stub.session_state.auto_approve is False


def test_global_auto_approve_untouched():
    # User had auto-approve on globally (not plan-scoped) -> keep it.
    stub, _ = _stub("# P", auto_approve=True, scoped=False)
    asyncio.run(NovaApp._maybe_run_approved_plan(stub))
    assert stub.session_state.auto_approve is True
