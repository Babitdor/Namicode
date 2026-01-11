# Implementation Plan: First-Run Onboarding Flow

## Overview

Implement a secure, user-friendly onboarding workflow for the Nami CLI that collects API keys and provider configuration on first run. The implementation will follow Claude Code principles: no secrets in repo, secure storage outside project root, and a clean split between configuration and secrets.

## Design Approach

### 1. Secret Storage Strategy

**Primary: OS Keychain (using keyring library)**
- Add `keyring` to dependencies in pyproject.toml
- Store secrets with namespace "nami" and keys like "tavily_api_key", "openai_api_key", etc.
- Cross-platform support: macOS Keychain, Windows Credential Manager, Linux Secret Service

**Fallback: Permission-restricted file**
- If keyring is unavailable, use `~/.nami/secrets.json` with chmod 600
- Show warning to user about fallback storage method

### 2. Configuration Split

**Non-secret config: `~/.nami/config.json`**
```json
{
  "provider": "ollama",
  "ollama": {
    "host": "http://localhost:11434",
    "default_model": "qwen2.5-coder:32b"
  },
  "search": {
    "provider": "tavily"
  },
  "onboarding_completed": true
}
```

**Secret storage: OS keychain or `~/.nami/secrets.json`**
- Keys: `tavily_api_key`, `openai_api_key`, `anthropic_api_key`, `google_api_key`, `groq_api_key`
- Never printed to terminal or logged

### 3. First-Run Detection

Check on CLI startup (in `cli_main()` in main.py):
```python
if not config_file_exists() and not args.command == "init":
    console.print("[yellow]First run detected. Running onboarding...[/yellow]")
    run_onboarding_wizard()
```

## Implementation Steps

### Phase 1: Core Infrastructure

**File: `namicode_cli/onboarding.py` (NEW)**

1. **Create SecretManager class**
   - Method: `store_secret(key: str, value: str) -> bool`
   - Method: `get_secret(key: str) -> str | None`
   - Method: `delete_secret(key: str) -> bool`
   - Method: `list_secrets() -> list[str]`
   - Implementation:
     ```python
     try:
         import keyring
         use_keyring = True
     except ImportError:
         use_keyring = False
         # Fall back to encrypted file or plain JSON with chmod 600
     ```

2. **Create OnboardingWizard class**
   - Method: `run() -> bool` - Main wizard flow
   - Method: `_prompt_provider() -> str` - Interactive provider selection
   - Method: `_prompt_provider_config(provider: str) -> dict` - Provider-specific setup
   - Method: `_prompt_tavily_key() -> str` - Tavily API key with hidden input
   - Method: `_test_connections(config: dict) -> bool` - Validate setup
   - Method: `_save_config(config: dict) -> None` - Write to config.json and keychain

3. **Interactive prompts using prompt_toolkit**
   - Use `PromptSession` with custom completers for provider selection
   - Use `prompt(is_password=True)` for API key input (hidden)
   - Display provider options with numbered menu:
     ```
     Choose LLM provider:
       1. Ollama (local)
       2. OpenAI
       3. Anthropic
       4. Groq
     ```

4. **Connection testing**
   - For Ollama: Send GET request to `{host}/api/tags`
   - For cloud providers: Try to create model instance and validate
   - For Tavily: Send test search query
   - Show real-time status: `Testing Ollama connection... ✓`

### Phase 2: Settings Integration

**File: `namicode_cli/config.py` (MODIFY)**

1. **Update Settings.from_environment() method** (lines 328-366)
   - Add keychain check before environment variables
   - Priority order: keyring → env vars → defaults
   ```python
   @classmethod
   def from_environment(cls, ...):
       secret_manager = SecretManager()

       # Check keyring first, then env vars
       openai_key = (
           secret_manager.get_secret("openai_api_key")
           or os.environ.get("OPENAI_API_KEY")
       )
       anthropic_key = (
           secret_manager.get_secret("anthropic_api_key")
           or os.environ.get("ANTHROPIC_API_KEY")
       )
       # ... etc for all API keys
   ```

2. **Add method: `get_onboarding_status() -> bool`**
   - Check if `~/.nami/config.json` exists
   - Check if `onboarding_completed` flag is True
   - Return combined status

3. **Add method: `mark_onboarding_complete()`**
   - Set `onboarding_completed: true` in config.json
   - Create `~/.nami/.onboarded` marker file

### Phase 3: CLI Commands

**File: `namicode_cli/commands.py` (MODIFY)**

1. **Enhance `/init` command** (lines 42-295)
   - Add `--onboarding` flag to trigger wizard
   - If run without flags and no config exists, run onboarding
   - Keep existing NAMI.md creation functionality

**File: `namicode_cli/main.py` (MODIFY)**

2. **Add `nami init` subcommand** (in parse_args(), lines 134-269)
   ```python
   init_parser = subparsers.add_parser("init", help="Run first-time setup")
   init_parser.add_argument("--reset", action="store_true",
                           help="Re-run onboarding wizard")
   ```

3. **Add `nami config` subcommand**
   ```python
   config_parser = subparsers.add_parser("config", help="View or edit configuration")
   config_parser.add_argument("command", nargs="?", choices=["show", "set", "get"])
   config_parser.add_argument("key", nargs="?")
   config_parser.add_argument("value", nargs="?")
   ```

4. **Add `nami secrets` subcommand**
   ```python
   secrets_parser = subparsers.add_parser("secrets", help="Manage API keys")
   secrets_parser.add_argument("command", choices=["set", "list", "delete"])
   secrets_parser.add_argument("key", nargs="?")
   ```

5. **Add `nami doctor` subcommand**
   ```python
   doctor_parser = subparsers.add_parser("doctor", help="Validate setup")
   ```

**File: `namicode_cli/doctor.py` (NEW)**

6. **Create doctor command implementation**
   - Check: Config file exists
   - Check: Required secrets are set
   - Check: Can connect to LLM provider
   - Check: Can connect to Tavily
   - Check: File permissions on secrets.json (if used)
   - Output rich formatted report with ✓/✗ status

### Phase 4: Startup Flow Integration

**File: `namicode_cli/main.py` (MODIFY)**

1. **Modify cli_main()** (lines 1008-1067)
   - Add first-run detection at the top:
   ```python
   def cli_main():
       # Parse args first
       args = parse_args()

       # Check for first run (unless running init command)
       if args.command != "init":
           settings = Settings.from_environment()
           if not settings.get_onboarding_status():
               console.print("[yellow]→ First run detected[/yellow]")
               console.print()
               wizard = OnboardingWizard()
               if wizard.run():
                   console.print("[green]✓ Setup complete![/green]")
                   console.print()
               else:
                   console.print("[red]✗ Setup incomplete[/red]")
                   console.print("Run 'nami init' to try again")
                   return 1

       # Continue with normal command routing
       if args.command == "init":
           # ... existing logic
   ```

### Phase 5: Testing & Error Handling

**File: `tests/unit_tests/test_onboarding.py` (NEW)**

1. **Test SecretManager**
   - Test keyring storage and retrieval
   - Test fallback to file storage
   - Test error handling for missing keyring

2. **Test OnboardingWizard** (mocked)
   - Test provider selection flow
   - Test config generation
   - Test connection validation
   - Test error handling for invalid inputs

3. **Test Settings integration**
   - Test keyring priority over env vars
   - Test fallback to env vars when keyring empty
   - Test onboarding status detection

**File: `namicode_cli/errors.py` (MODIFY if needed)**

4. **Add onboarding-specific errors**
   - `OnboardingIncompleteError`
   - `ConnectionTestFailedError`
   - `SecretStorageError`

## File Changes Summary

### New Files
1. `namicode_cli/onboarding.py` - Core onboarding wizard and secret manager
2. `namicode_cli/doctor.py` - Setup validation command
3. `tests/unit_tests/test_onboarding.py` - Onboarding tests

### Modified Files
1. `namicode_cli/config.py` - Settings integration with keyring
2. `namicode_cli/main.py` - CLI startup flow and subcommands
3. `namicode_cli/commands.py` - Enhanced /init command
4. `pyproject.toml` - Add keyring dependency

### New Config Files (created by onboarding)
1. `~/.nami/config.json` - Non-secret configuration
2. `~/.nami/.onboarded` - Completion marker
3. `~/.nami/secrets.json` - Fallback secret storage (if keyring unavailable)

## Dependencies

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing deps
    "keyring>=24.0.0",  # OS keychain integration
]
```

## User Experience Flow

### First Run
```
$ nami

→ First run detected

Welcome to Nami 👋

Let's set up your AI coding assistant.

✓ Choose LLM provider:
  1. Ollama (local)
  2. OpenAI
  3. Anthropic
  4. Groq

> 1

✓ Ollama configuration:
  Host [http://localhost:11434]:

✓ Search provider:
  Tavily API key: ********

✓ Testing connections:
  → Ollama ping... ✓
  → Tavily query... ✓

✓ Setup complete!

Configuration saved to ~/.nami/config.json
API keys stored in system keychain

You're ready to go! Try: nami "help me build a web scraper"
```

### Re-running onboarding
```
$ nami init --reset

This will overwrite your current configuration.
Continue? [y/N]: y

# ... runs wizard again
```

### Checking status
```
$ nami doctor

Nami Setup Validation
─────────────────────

✓ Configuration file found
✓ LLM provider configured (ollama)
✓ Tavily API key set
✓ Ollama connection successful
✓ Tavily connection successful

Everything looks good! 🎉
```

### Managing secrets
```
$ nami secrets list
Configured API keys:
  - tavily_api_key
  - openai_api_key

$ nami secrets set anthropic_api_key
Enter API key: ********
✓ API key saved to system keychain

$ nami secrets delete openai_api_key
✓ API key removed
```

## Security Considerations

1. **Never log or print API keys** - All secret handling uses masked input
2. **File permissions** - If using fallback file storage, set chmod 600 on secrets.json
3. **Keychain validation** - Test keyring availability before use, handle gracefully if unavailable
4. **No defaults for secrets** - Never provide default API keys or commit them to repo
5. **Separate storage** - Keep secrets out of ~/.nami/config.json entirely

## Migration Path

For users with existing .env files:
1. On first run, check for .env with API keys
2. Prompt: "Found existing API keys in .env. Import to secure storage? [Y/n]"
3. If yes, migrate keys to keychain and show warning about removing from .env
4. Never auto-delete .env (user might have other vars there)

## Testing Checklist

- [ ] First run triggers onboarding automatically
- [ ] Can complete onboarding with Ollama (no API key required)
- [ ] Can complete onboarding with OpenAI (API key required)
- [ ] Can complete onboarding with Anthropic (API key required)
- [ ] Connection tests fail gracefully with clear error messages
- [ ] API keys stored in keyring successfully
- [ ] API keys retrieved from keyring on startup
- [ ] Fallback to file storage works if keyring unavailable
- [ ] `nami doctor` validates all connections
- [ ] `nami config` shows non-secret config only
- [ ] `nami secrets set` updates keys securely
- [ ] Settings.from_environment() uses keyring first
- [ ] Can re-run onboarding with `nami init --reset`
- [ ] Migration from .env works correctly
- [ ] Windows, macOS, Linux compatibility

## Success Criteria

1. ✅ Users can set up Nami without touching .env files
2. ✅ API keys never appear in plaintext on screen
3. ✅ Secrets stored in OS keychain (or secure fallback)
4. ✅ Configuration split between config.json and secrets
5. ✅ Onboarding is non-blocking and resumable
6. ✅ Works with local (Ollama) and cloud providers
7. ✅ Clear error messages and validation
8. ✅ Easy to update configuration after initial setup
