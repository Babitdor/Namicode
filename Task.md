## Task

The **very first-run onboarding flow** for the nami agentic coding CLI, where the user must provide:

* Tavily Search API key
* LLM provider choice
* Provider-specific config (e.g. Ollama host, or cloud API keys)

Below is a **clean, secure, Claude-Code–style onboarding design** that fits your setup and avoids risky key handling.

---

## Goal of onboarding

1. **Collect required credentials once**
2. **Store them securely**
3. **Never require plaintext keys in repo files**
4. **Be non-blocking and resumable**
5. **Work across local + cloud providers**

---

## Core principles (important)

* ❌ No API keys committed in `.env`
* ❌ No API keys printed back to terminal
* ✅ Secrets stored outside project root
* ✅ Provider-agnostic config format
* ✅ Can re-run onboarding safely

---

## What you should collect (minimum)

### 1. Search tool

* Tavily API key

### 2. LLM provider

* Provider name:

  * `ollama`
  * `openai`
  * `anthropic`
  * `groq`
  * etc.

### 3. Provider-specific config

**Ollama**

* Host (default: `http://localhost:11434`)
* Default model (optional)

**Cloud providers**

* API key
* Optional org / project id
* Optional base URL

---

## Where to store secrets (IMPORTANT)

### Recommended layout

```
~/.nami/
  ├── config.json          # non-secret config
  ├── secrets.json         # encrypted or OS-protected
  ├── sessions/
  └── cache/
```

### Split config vs secrets

#### `config.json` (safe)

```json
{
  "provider": "ollama",
  "ollama": {
    "host": "http://localhost:11434"
  },
  "search": {
    "provider": "tavily"
  }
}
```

#### `secrets.json` (never printed)

```json
{
  "tavily_api_key": "****",
  "openai_api_key": "****"
}
```

---

## How to store secrets securely (ranked)

### 🥇 Best (recommended)

**OS keychain**

* macOS → Keychain
* Linux → Secret Service (libsecret)
* Windows → Credential Manager

Python options:

* `keyring` (cross-platform, simple)

Example:

```python
keyring.set_password("nami", "tavily_api_key", key)
```

### 🥈 Acceptable (fallback)

* Encrypted `secrets.json`
* Master password stored in OS keychain

### 🥉 Last resort

* Plaintext `~/.nami/secrets.json`
* File permission: `chmod 600`

---

## First-run onboarding workflow

### 1. Detect first run

```text
If ~/.nami/config.json does not exist → onboarding
```

### 2. Interactive CLI wizard

```
Welcome to Nami 👋

✔ Choose LLM provider:
  1. Ollama (local)
  2. OpenAI
  3. Anthropic
  4. Groq

✔ Provider config:
  - Ollama host [http://localhost:11434]:

✔ Search provider:
  - Tavily API key: (hidden input)

✔ Test connections:
  - Ollama ping ✔
  - Tavily query ✔
```

### 3. Store config + secrets

* Config → `config.json`
* Secrets → keyring

### 4. Write onboarding completion marker

```text
~/.nami/.onboarded
```

---

## CLI commands you should support

```bash
nami init              # first-time onboarding
nami config            # view non-secret config
nami config set        # update provider/host
nami secrets set       # update API keys
nami doctor            # validate setup
```

---

## How Claude Code does it (important insight)

Claude Code:

* **Never stores keys in repo**
* Relies on:

  * OS keychain
  * Environment variables
* Uses a **minimal bootstrap prompt**
* Rehydrates state dynamically

👉 Your approach is already **more advanced** than Claude Code by having:

* Session persistence
* Repo compatibility checks
* Agent memory

---
