# Nova Code

Domain language for the Nova coding-agent CLI/TUI. Started 2026-07-08 during
the architecture review; grows as deepening refactors name new concepts.

## Language

**Model Builder**:
The single constructor for provider chat models — `build_chat_model(provider, model_name)` in `config/model_create.py`. Every `ChatOpenAI`/`ChatAnthropic`/`ChatOllama`/… in Nova is built here; reasoning effort, thinking budgets, retries, and Ollama patches are its internals.
_Avoid_: model factory, provider factory, per-call-site `ChatX(...)` construction

**Key Policy**:
What a caller does when a provider's API key is missing — return `None` (vision captioning), warn and fall back (boot), or raise (explicit model switch). Belongs to the caller, never to the Model Builder.
_Avoid_: key validation (inside construction code)

**Command Table**:
The single registry of TUI slash commands — `TUI_COMMANDS` in `tui/app.py`. Autocomplete, dispatch, and `/help` are derivations of it; a command exists in exactly one place. Plugin commands append to the derived autocomplete list at registration.
_Avoid_: per-view command lists, elif dispatch chains, hand-written help entries
