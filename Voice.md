> ## Documentation Index
>
> Fetch the complete documentation index at: https://visionagents.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice Agents

> Build voice agents with realtime models or custom STT/LLM/TTS pipelines

Build voice agents with swappable providers, [phone integration](/guides/calling), [function calling](/guides/mcp-tool-calling), and [production deployment](/guides/deployment) with [built-in metrics](/core/telemetry).

<Prompt description="Copy this prompt into Claude Code, Cursor, Windsurf, or any coding agent to scaffold your project." actions={["copy", "cursor"]}>
{`Create a Python project for a Vision Agents custom voice pipeline using uv and Python 3.12.

    Steps:
    1. Initialize: uv init && uv add "vision-agents[getstream,gemini,deepgram,elevenlabs]" python-dotenv
    2. Create .env with: STREAM_API_KEY, STREAM_API_SECRET (from getstream.io), GOOGLE_API_KEY (from aistudio.google.com), DEEPGRAM_API_KEY (from deepgram.com), ELEVENLABS_API_KEY (from elevenlabs.io)
    3. Create main.py:

    from dotenv import load_dotenv
    from vision_agents.core import Agent, AgentLauncher, User, Runner
    from vision_agents.plugins import getstream, gemini, deepgram, elevenlabs

    load_dotenv()

    def setup_llm():
      llm = gemini.LLM()

      @llm.register_function(description="Get current weather for a location")
      async def get_weather(location: str) -> dict:
          return {"temperature": "22C", "condition": "Sunny", "location": location}

      return llm

    async def create_agent(**kwargs) -> Agent:
      return Agent(
          edge=getstream.Edge(),
          agent_user=User(name="Assistant", id="agent"),
          instructions="You're a helpful voice assistant with access to tools. Be concise.",
          llm=setup_llm(),
          stt=deepgram.STT(eager_turn_detection=True),
          tts=elevenlabs.TTS(),
      )

    async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
      call = await agent.create_call(call_type, call_id)
      async with agent.join(call):
          await agent.simple_response("Greet the user and let them know you can check the weather")
          await agent.finish()

    if __name__ == "__main__":
      Runner(AgentLauncher(create_agent=create_agent, join_call=join_call)).cli()

    4. Run with: uv run main.py run

    Reference docs: https://visionagents.ai
    MCP server: https://visionagents.ai/mcp
    Skill.md: https://visionagents.ai/skill.md`}

</Prompt>

<Info>
  Vision Agents requires a [Stream](https://getstream.io/try-for-free/) account for real-time transport. Stream offers 333,000 free participant minutes monthly, plus additional credits through the [Maker Program](https://getstream.io/chat/pricing/#free-for-maker) for indie developers. Most AI providers also offer free tiers.
</Info>

**Prerequisites:** Complete the [Quickstart](/introduction/quickstart) first.

## Two Modes

| Mode                | Best For                        |
| ------------------- | ------------------------------- |
| **Realtime Models** | Fastest path, built-in STT/TTS  |
| **Custom Pipeline** | Full control over STT, LLM, TTS |

**Realtime models** like `openai.Realtime()` and `gemini.Realtime()` handle speech-to-speech natively via WebRTC or WebSocket — no separate STT/TTS needed. The [Quickstart](/introduction/quickstart) uses this approach.

**Custom pipelines** let you mix providers: Deepgram for STT, any LLM, ElevenLabs for TTS, with configurable turn detection.

## Custom Pipeline Mode

For granular control over your voice pipeline, use separate STT, LLM, and TTS components. Add the additional plugins beyond the quickstart:

```bash theme={null}
uv add "vision-agents[deepgram,elevenlabs]"
```

Add these keys to your `.env`:

```bash theme={null}
DEEPGRAM_API_KEY=your_deepgram_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
```

Then update your agent to use the custom pipeline:

```python theme={null}
from dotenv import load_dotenv

from vision_agents.core import Agent, AgentLauncher, User, Runner
from vision_agents.plugins import getstream, gemini, deepgram, elevenlabs

load_dotenv()


async def create_agent(**kwargs) -> Agent:
    return Agent(
        edge=getstream.Edge(),
        agent_user=User(name="Assistant", id="agent"),
        instructions="You're a helpful voice assistant.",
        llm=gemini.LLM(),
        stt=deepgram.STT(eager_turn_detection=True),
        tts=elevenlabs.TTS(),
    )


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    call = await agent.create_call(call_type, call_id)
    async with agent.join(call):
        await agent.simple_response("Greet the user")
        await agent.finish()


if __name__ == "__main__":
    Runner(AgentLauncher(create_agent=create_agent, join_call=join_call)).cli()
```

Mix and match any combination:

| Component          | Options                                                        |
| ------------------ | -------------------------------------------------------------- |
| **LLM**            | Gemini, OpenAI, OpenRouter, Anthropic, Grok, HuggingFace       |
| **STT**            | Deepgram, ElevenLabs, Fast-Whisper, Fish, Wizper               |
| **TTS**            | ElevenLabs, Cartesia, Deepgram, Pocket, AWS Polly              |
| **Turn Detection** | Deepgram (built-in), ElevenLabs (built-in), Smart Turn, Vogent |

## Function Calling & MCP

Register functions that your agent can call:

```python theme={null}
@llm.register_function(description="Get weather for a location")
async def get_weather(location: str) -> dict:
    return {"temperature": "22C", "condition": "Sunny"}
```

Functions are automatically converted to the right format for each LLM provider. For MCP servers, external tools, and advanced patterns, see the [Function Calling & MCP guide](/guides/mcp-tool-calling).

## What's Next

<CardGroup cols={2}>
  <Card title="Phone Integration" icon="phone" href="/guides/calling">
    Connect agents to Twilio for inbound and outbound calls
  </Card>

  <Card title="RAG Support" icon="database" href="/guides/rag">
    Add knowledge bases with Gemini FileSearch or TurboPuffer
  </Card>

  <Card title="Docker Deployment" icon="docker" href="/guides/deployment">
    Docker setup and environment configuration
  </Card>

  <Card title="Built-in HTTP Server" icon="globe" href="/guides/http-server">
    Console mode and HTTP server for running agents
  </Card>
</CardGroup>

## Examples

- [Simple Agent](/examples/simple-agent) — Minimal voice agent with Deepgram STT + ElevenLabs TTS + Gemini LLM
- [Phone & RAG](/examples/phone-and-rag) — Twilio calling with TurboPuffer knowledge base

Built with [Mintlify](https://mintlify.com).
