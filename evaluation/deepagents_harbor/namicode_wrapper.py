"""A wrapper for Nami Code CLI to run in Harbor evaluation environments.

This wrapper integrates the full Nami Code agent with all middleware
(FileTracker, SharedMemory, etc.) for comprehensive evaluation.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from langchain.messages import UsageMetadata
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langsmith import trace

# Load .env file if present
load_dotenv()

from deepagents_harbor.backend import HarborSandbox
from deepagents_harbor.tracing import create_example_id_from_instruction

# Import Nami Code components
from namicode_cli.agents.core_agent import create_agent_with_config
from namicode_cli.tracking.file_tracker import reset_session_tracker
from namicode_cli.config.model_manager import ModelManager, MODEL_PRESETS, ProviderType
from namicode_cli.tools import fetch_url, http_request
from namicode_cli.server_runner.dev_server import list_servers_tool, start_dev_server_tool, stop_server_tool
from namicode_cli.server_runner.test_runner import run_tests_tool


class NamiCodeWrapper(BaseAgent):
    """Harbor agent implementation using the full Nami Code CLI agent.

    This wrapper uses create_agent_with_config from namicode_cli to create
    a fully-featured agent with all middleware (FileTracker, SharedMemory, etc.).
    """

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        temperature: float = 0.0,
        verbose: bool = True,
        provider: ProviderType | None = None,
        *args,
        **kwargs,
    ) -> None:
        """Initialize NamiCodeWrapper.

        Args:
            logs_dir: Directory for storing logs
            model_name: Name of the LLM model to use (optional, uses configured model)
            temperature: Temperature setting for the model
            verbose: Enable verbose output
            provider: Model provider (openai, anthropic, ollama, google).
                      If None, uses the configured provider from nami.config.json or env.
        """
        super().__init__(logs_dir, model_name, *args, **kwargs)

        # Initialize model manager to get configured provider/model
        model_manager = ModelManager()

        # Determine provider and model
        if provider is None and model_name is None:
            # Use configured provider/model from nami.config.json or env
            current = model_manager.get_current_provider()
            if current:
                provider_name, configured_model = current
                # Map display name back to provider ID
                provider = self._get_provider_id(provider_name)
                model_name = configured_model
            else:
                # Fallback to Ollama if nothing configured
                provider = "ollama"
                model_name = MODEL_PRESETS["ollama"]["default_model"]
        elif provider is not None and model_name is None:
            # Provider specified but no model - use default for that provider
            model_name = MODEL_PRESETS[provider]["default_model"]
        elif provider is None and model_name is not None:
            # Model specified but no provider - try to infer from model name
            provider = self._infer_provider(model_name)

        self._provider: ProviderType = provider or "ollama"
        self._model_name = model_name or MODEL_PRESETS[self._provider]["default_model"]
        self._temperature = temperature
        self._verbose = verbose

        # Create model using ModelManager for consistent configuration
        self._model: BaseChatModel = model_manager.create_model_for_provider(
            self._provider, self._model_name
        )

        # LangSmith run tracking
        self._langsmith_run_id: str | None = None
        self._task_name: str | None = None

    @staticmethod
    def _get_provider_id(provider_name: str) -> ProviderType:
        """Convert display name to provider ID."""
        name_map = {
            "OpenAI": "openai",
            "Anthropic": "anthropic",
            "Ollama": "ollama",
            "Google": "google",
        }
        return name_map.get(provider_name, "ollama")  # type: ignore

    @staticmethod
    def _infer_provider(model_name: str) -> ProviderType:
        """Infer provider from model name."""
        model_lower = model_name.lower()
        if "gpt" in model_lower or "o1" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "gemini" in model_lower:
            return "google"
        else:
            # Default to Ollama for unknown models (likely local)
            return "ollama"

    @staticmethod
    def name() -> str:
        return "namicode-harbor"

    async def setup(self, environment: BaseEnvironment) -> None:
        """Setup the agent with the given environment."""
        # Reset session tracker for clean evaluation
        reset_session_tracker()

    def version(self) -> str | None:
        """The version of the agent."""
        return "0.1.0"

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        """Execute the Nami Code agent on the given instruction.

        Args:
            instruction: The task to complete
            environment: Harbor environment (Docker, Modal, etc.)
            context: Context to populate with metrics
        """
        configuration = json.loads(environment.trial_paths.config_path.read_text())
        if not isinstance(configuration, dict):
            raise AssertionError(
                f"Unexpected configuration format. Expected dict, got {type(configuration)}."
            )

        # Create Harbor sandbox backend
        backend = HarborSandbox(environment)

        # Create tools list for the agent
        tools = [
            http_request,
            fetch_url,
            run_tests_tool,
            start_dev_server_tool,
            stop_server_tool,
            list_servers_tool,
        ]

        # Create Nami Code agent with full middleware stack
        # Note: We use the sandbox backend for file operations
        nami_agent, _ = create_agent_with_config(
            model=self._model,
            assistant_id=f"nami-eval-{environment.session_id}",
            tools=tools,
            sandbox=backend,
            sandbox_type="harbor",
        )

        # Build metadata
        metadata = {
            "task_instruction": instruction,
            "model": self._model_name,
            "harbor_session_id": environment.session_id,
            "agent_mode": "namicode-full",
            "wrapper": "NamiCodeWrapper",
        }
        metadata.update(configuration)

        # Compute example_id for LangSmith linking
        example_id = create_example_id_from_instruction(instruction)

        config: RunnableConfig = {
            "run_name": f"nami-{environment.session_id}",
            "tags": [
                self._model_name,
                environment.session_id,
                "namicode",
                "evaluation",
            ],
            "configurable": {
                "thread_id": str(uuid.uuid4()),
            },
        }

        # Run with LangSmith tracing if configured
        langsmith_experiment_name = os.environ.get("LANGSMITH_EXPERIMENT", "").strip() or None

        if langsmith_experiment_name:
            with trace(
                name=f"nami-{environment.session_id}",
                reference_example_id=example_id,
                inputs={"instruction": instruction},
                project_name=langsmith_experiment_name,
                metadata=metadata,
            ) as run_tree:
                result = await nami_agent.ainvoke(
                    {"messages": [{"role": "user", "content": instruction}]},
                    config=config,
                )
                # Extract last AI message for output
                last_message = result["messages"][-1]
                if isinstance(last_message, AIMessage):
                    run_tree.end(outputs={"last_message": last_message.text})
        else:
            config["metadata"] = metadata
            result = await nami_agent.ainvoke(
                {"messages": [{"role": "user", "content": instruction}]},
                config=config,
            )

        # Save trajectory for Harbor analysis
        self._save_trajectory(environment, instruction, result)

    def _save_trajectory(
        self, environment: BaseEnvironment, instruction: str, result: dict
    ) -> None:
        """Save current trajectory to logs directory in ATIF format."""
        total_prompt_tokens = 0
        total_completion_tokens = 0

        # Create initial step from user instruction
        steps = [
            Step(
                step_id=1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                source="user",
                message=instruction,
            ),
        ]

        observations = []
        pending_step: Step | None = None

        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                # Extract token usage
                usage: UsageMetadata = msg.usage_metadata
                if usage:
                    total_prompt_tokens += usage.get("input_tokens", 0)
                    total_completion_tokens += usage.get("output_tokens", 0)

                # Process pending step with observations
                if pending_step is not None:
                    if pending_step.tool_calls and observations:
                        pending_step.observation = Observation(results=observations)
                        observations = []
                    steps.append(pending_step)
                    pending_step = None

                # Extract content and tool calls
                atf_tool_calls = []
                message = ""

                content_blocks = getattr(msg, 'content_blocks', None)
                if content_blocks:
                    for cb in content_blocks:
                        if cb.get("type") == "text":
                            message += cb.get("text", "")
                        elif cb.get("type") == "reasoning":
                            message += cb.get("reasoning", "")
                        elif cb.get("type") == "tool_call":
                            atf_tool_calls.append(
                                ToolCall(
                                    tool_call_id=cb.get("id", ""),
                                    function_name=cb.get("name", ""),
                                    arguments=cb.get("args", {}),
                                )
                            )
                elif isinstance(msg.content, str):
                    message = msg.content
                elif isinstance(msg.content, list):
                    for item in msg.content:
                        if isinstance(item, str):
                            message += item
                        elif isinstance(item, dict) and item.get("type") == "text":
                            message += item.get("text", "")

                # Also check tool_calls attribute
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tc in msg.tool_calls:
                        atf_tool_calls.append(
                            ToolCall(
                                tool_call_id=tc.get("id", ""),
                                function_name=tc.get("name", ""),
                                arguments=tc.get("args", {}),
                            )
                        )

                new_step = Step(
                    step_id=steps[-1].step_id + 1 if steps else 1,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    source="agent",
                    message=message,
                    tool_calls=atf_tool_calls if atf_tool_calls else None,
                )

                if atf_tool_calls:
                    pending_step = new_step
                else:
                    steps.append(new_step)

            elif isinstance(msg, ToolMessage):
                observations.append(
                    ObservationResult(
                        source_call_id=msg.tool_call_id,
                        content=str(msg.content),
                    )
                )

            elif isinstance(msg, HumanMessage):
                # Skip - already handled initial instruction
                pass

        # Add remaining pending step
        if pending_step is not None:
            if pending_step.tool_calls and observations:
                pending_step.observation = Observation(results=observations)
            steps.append(pending_step)

        # Build trajectory
        metrics = FinalMetrics(
            total_prompt_tokens=total_prompt_tokens or None,
            total_completion_tokens=total_completion_tokens or None,
            total_steps=len(steps),
        )

        trajectory = Trajectory(
            schema_version="ATIF-v1.2",
            session_id=environment.session_id,
            agent=Agent(
                name=self.name(),
                version=self.version() or "unknown",
                model_name=self._model_name,
                extra={
                    "framework": "namicode-cli",
                    "middleware": [
                        "FileTrackerMiddleware",
                        "AgentMemoryMiddleware",
                        "SharedMemoryMiddleware",
                        "ShellMiddleware",
                    ],
                },
            ),
            steps=steps,
            final_metrics=metrics,
        )

        trajectory_path = self.logs_dir / "trajectory.json"
        trajectory_path.write_text(json.dumps(trajectory.to_json_dict(), indent=2))
