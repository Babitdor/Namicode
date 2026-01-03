"""Setup script for namicode-cli."""
from pathlib import Path
from setuptools import setup, find_packages

# Check if nami-deepagents directory exists for local development
nami_path = Path(__file__).parent / "deepagents-nami"
has_local_nami = nami_path.exists()

# Prepare dependencies
if has_local_nami:
    # Local development: use local path
    nami_uri = nami_path.resolve().as_uri()
    nami_dep = f"nami-deepagents @ {nami_uri}"
    print(f"[setup.py] Using local nami-deepagents: {nami_dep}")
else:
    # Production/PyPI: use PyPI version
    nami_dep = "nami-deepagents>=0.2.8"
    print(f"[setup.py] Using PyPI nami-deepagents: {nami_dep}")

dependencies = [
    nami_dep,
    "requests",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.52",
    "langchain-openai>=0.1.0",
    "tavily-python",
    "python-dotenv",
    "daytona>=0.113.0",
    "modal>=0.65.0",
    "markdownify>=0.13.0",
    "langchain>=1.0.7",
    "runloop-api-client>=0.69.0",
    "langchain-ollama>=1.0.0",
    "langchain-google-genai>=3.2.0",
    "transformers>=4.57.3",
    "mcp>=1.0.0",
    "docker>=7.0.0",
    "langchain-mcp-adapters>=0.1.0",
]

setup(
    name="namicode-cli",
    version="0.0.10",
    description="Namicode CLI - AI coding assistant",
    readme="README.md",
    license="MIT",
    python_requires=">=3.11,<4.0",
    packages=find_packages(exclude=["tests", "tests.*", "deepagents-nami"]),
    install_requires=dependencies,
    entry_points={
        "console_scripts": [
            "nami=namicode_cli:cli_main",
        ],
    },
    package_data={
        "namicode_cli": ["default_agent_prompt.md", "py.typed"],
    },
)
