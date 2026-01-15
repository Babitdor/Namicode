from nami_deepagents import create_deep_agent
from namicode_cli.config.model_create import create_model
from nami_deepagents.backends.filesystem import FilesystemBackend

skill_creation_agent = create_deep_agent(
    name="Skill-Creation-Agent",
    model=create_model(),
    system_prompt="""You are a sarcastic assistant""",
    backend=FilesystemBackend(),
)

response = skill_creation_agent.invoke(
            {"messages": [{"role": "user", "content": "Can you help ? "}]}
        )

print(response)