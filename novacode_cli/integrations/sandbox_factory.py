"""Sandbox lifecycle management with context managers."""

import os
import shlex
import string
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from deepagents.backends.protocol import SandboxBackendProtocol

from novacode_cli.config.config import console

# Only these env vars are allowed in setup script template substitution.
# Prevents accidental leakage of API keys and secrets.
_ALLOWED_SETUP_VARS = {"HOME", "USER", "PATH", "SHELL", "LANG", "LC_ALL", "TERM"}


def _run_sandbox_setup(backend: SandboxBackendProtocol, setup_script_path: str) -> None:
    """Run users setup script in sandbox with env var expansion.

    Args:
        backend: Sandbox backend instance
        setup_script_path: Path to setup script file
    """
    script_path = Path(setup_script_path).resolve()

    # Prevent path traversal - script must be under current working directory or home
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    if not (script_path.is_relative_to(cwd) or script_path.is_relative_to(home)):
        msg = (
            f"Setup script must be under working directory or home: {setup_script_path}"
        )
        raise ValueError(msg)

    if not script_path.exists():
        msg = f"Setup script not found: {setup_script_path}"
        raise FileNotFoundError(msg)

    console.print(f"[dim]Running setup script: {setup_script_path}...[/dim]")

    # Read script content
    script_content = script_path.read_text()

    # Expand ${VAR} syntax using only allowlisted environment variables
    template = string.Template(script_content)
    safe_env = {k: v for k, v in os.environ.items() if k in _ALLOWED_SETUP_VARS}
    expanded_script = template.safe_substitute(safe_env)

    # Execute in sandbox with 5-minute timeout
    result = backend.execute(f"bash -c {shlex.quote(expanded_script)}")

    if result.exit_code != 0:
        console.print(f"[red]❌ Setup script failed (exit {result.exit_code}):[/red]")
        console.print(f"[dim]{result.output}[/dim]")
        msg = "Setup failed - aborting"
        raise RuntimeError(msg)

    console.print("[green]✓ Setup complete[/green]")


@contextmanager
def create_modal_sandbox(
    *, sandbox_id: str | None = None, setup_script_path: str | None = None
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to Modal sandbox.

    Args:
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        (ModalBackend, sandbox_id)

    Raises:
        ImportError: Modal SDK not installed
        Exception: Sandbox creation/connection failed
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed
    """
    import modal

    from novacode_cli.integrations.modal import ModalBackend

    console.print("[yellow]Starting Modal sandbox...[/yellow]")

    # Create ephemeral app (auto-cleans up on exit)
    app = modal.App("deepagents-sandbox")

    with app.run():
        if sandbox_id:
            sandbox = modal.Sandbox.from_id(sandbox_id=sandbox_id)
            should_cleanup = False
        else:
            sandbox = modal.Sandbox.create(app=app, workdir="/workspace")
            should_cleanup = True

            # Poll until running (Modal requires this)
            for _ in range(90):  # 180s timeout (90 * 2s)
                if sandbox.poll() is not None:  # Sandbox terminated unexpectedly
                    msg = "Modal sandbox terminated unexpectedly during startup"
                    raise RuntimeError(msg)
                # Check if sandbox is ready by attempting a simple command
                try:
                    process = sandbox.exec("echo", "ready", timeout=5)
                    process.wait()
                    if process.returncode == 0:
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                # Timeout - cleanup and fail
                sandbox.terminate()
                msg = "Modal sandbox failed to start within 180 seconds"
                raise RuntimeError(msg)

        backend = ModalBackend(sandbox)
        console.print(f"[green]✓ Modal sandbox ready: {backend.id}[/green]")

        # Run setup script if provided
        if setup_script_path:
            _run_sandbox_setup(backend, setup_script_path)
        try:
            yield backend
        finally:
            if should_cleanup:
                try:
                    console.print(
                        f"[dim]Terminating Modal sandbox {sandbox_id}...[/dim]"
                    )
                    sandbox.terminate()
                    console.print(f"[dim]✓ Modal sandbox {sandbox_id} terminated[/dim]")
                except Exception as e:
                    console.print(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


@contextmanager
def create_runloop_sandbox(
    *, sandbox_id: str | None = None, setup_script_path: str | None = None
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to Runloop devbox.

    Args:
        sandbox_id: Optional existing devbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        (RunloopBackend, devbox_id)

    Raises:
        ImportError: Runloop SDK not installed
        ValueError: RUNLOOP_API_KEY not set
        RuntimeError: Devbox failed to start within timeout
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed
    """
    from runloop_api_client import Runloop

    from novacode_cli.integrations.runloop import RunloopBackend

    bearer_token = os.environ.get("RUNLOOP_API_KEY")
    if not bearer_token:
        msg = "RUNLOOP_API_KEY environment variable not set"
        raise ValueError(msg)

    client = Runloop(bearer_token=bearer_token)

    console.print("[yellow]Starting Runloop devbox...[/yellow]")

    if sandbox_id:
        devbox = client.devboxes.retrieve(id=sandbox_id)
        should_cleanup = False
    else:
        devbox = client.devboxes.create()
        sandbox_id = devbox.id
        should_cleanup = True

        # Poll until running (Runloop requires this)
        for _ in range(90):  # 180s timeout (90 * 2s)
            status = client.devboxes.retrieve(id=devbox.id)
            if status.status == "running":
                break
            time.sleep(2)
        else:
            # Timeout - cleanup and fail
            client.devboxes.shutdown(id=devbox.id)
            msg = "Devbox failed to start within 180 seconds"
            raise RuntimeError(msg)

    console.print(f"[green]✓ Runloop devbox ready: {sandbox_id}[/green]")

    backend = RunloopBackend(devbox_id=devbox.id, client=client)

    # Run setup script if provided
    if setup_script_path:
        _run_sandbox_setup(backend, setup_script_path)
    try:
        yield backend
    finally:
        if should_cleanup:
            try:
                console.print(
                    f"[dim]Shutting down Runloop devbox {sandbox_id}...[/dim]"
                )
                client.devboxes.shutdown(id=devbox.id)
                console.print(f"[dim]✓ Runloop devbox {sandbox_id} terminated[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


@contextmanager
def create_daytona_sandbox(
    *, sandbox_id: str | None = None, setup_script_path: str | None = None
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create Daytona sandbox.

    Args:
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        (DaytonaBackend, sandbox_id)

    Note:
        Connecting to existing Daytona sandbox by ID may not be supported yet.
        If sandbox_id is provided, this will raise NotImplementedError.
    """
    from daytona import Daytona, DaytonaConfig

    from novacode_cli.integrations.daytona import DaytonaBackend

    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key:
        msg = "DAYTONA_API_KEY environment variable not set"
        raise ValueError(msg)

    if sandbox_id:
        msg = (
            "Connecting to existing Daytona sandbox by ID not yet supported. "
            "Create a new sandbox by omitting --sandbox-id."
        )
        raise NotImplementedError(msg)

    console.print("[yellow]Starting Daytona sandbox...[/yellow]")

    daytona = Daytona(DaytonaConfig(api_key=api_key))
    sandbox = daytona.create()
    sandbox_id = sandbox.id

    # Poll until running (Daytona requires this)
    for _ in range(90):  # 180s timeout (90 * 2s)
        # Check if sandbox is ready by attempting a simple command
        try:
            result = sandbox.process.exec("echo ready", timeout=5)
            if result.exit_code == 0:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        try:
            # Clean up if possible
            sandbox.delete()
        finally:
            msg = "Daytona sandbox failed to start within 180 seconds"
            raise RuntimeError(msg)

    backend = DaytonaBackend(sandbox)
    console.print(f"[green]✓ Daytona sandbox ready: {backend.id}[/green]")

    # Run setup script if provided
    if setup_script_path:
        _run_sandbox_setup(backend, setup_script_path)
    try:
        yield backend
    finally:
        console.print(f"[dim]Deleting Daytona sandbox {sandbox_id}...[/dim]")
        try:
            sandbox.delete()
            console.print(f"[dim]✓ Daytona sandbox {sandbox_id} terminated[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


@contextmanager
def create_docker_sandbox(
    *,
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    ports: dict[int, int] | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to Docker container sandbox.

    Args:
        sandbox_id: Optional existing container ID to reuse
        setup_script_path: Optional path to setup script to run after container starts
        ports: Optional port mapping as {container_port: host_port}.
               Example: {8080: 8080, 3000: 3000} maps container ports to same host ports.
               If None, no ports are exposed.

    Yields:
        DockerBackend instance

    Raises:
        ImportError: Docker SDK not installed
        Exception: Container creation/connection failed
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed
    """
    import docker

    from novacode_cli.integrations.docker import DockerBackend

    console.print("[yellow]Starting Docker container...[/yellow]")

    # Connect to Docker daemon
    try:
        client = docker.from_env()
    except Exception as e:
        msg = f"Failed to connect to Docker daemon: {e}\nIs Docker running?"
        raise RuntimeError(msg) from e

    container = None
    should_cleanup = True

    try:
        if sandbox_id:
            # Reuse existing container
            console.print(
                f"[dim]Connecting to existing container {sandbox_id}...[/dim]"
            )
            container = client.containers.get(sandbox_id)
            should_cleanup = False  # Don't cleanup reused containers

            # Ensure container is running
            if container.status != "running":
                console.print("[dim]Starting stopped container...[/dim]")
                container.start()

        else:
            # Create new container
            console.print("[dim]Creating new container...[/dim]")

            # Default image: Python with common tools
            image = "python:3.11-slim"

            # Pull image if not present
            try:
                client.images.get(image)
            except docker.errors.ImageNotFound:
                console.print(f"[dim]Pulling image {image}...[/dim]")
                client.images.pull(image)

            # Convert port mapping to Docker format
            # {8080: 8080} -> {'8080/tcp': 8080}
            port_bindings = None
            if ports:
                port_bindings = {
                    f"{container_port}/tcp": host_port
                    for container_port, host_port in ports.items()
                }
                console.print(f"[dim]Exposing ports: {ports}[/dim]")

            # Create and start container
            container = client.containers.run(
                image=image,
                command="sleep infinity",  # Keep container running
                detach=True,
                working_dir="/workspace",
                volumes={},
                environment={},
                stdin_open=True,
                tty=True,
                ports=port_bindings,  # Port forwarding
            )

            # Wait for container to be ready
            import time

            for _ in range(30):  # 30 second timeout
                container.reload()
                if container.status == "running":
                    break
                time.sleep(1)
            else:
                msg = "Docker container failed to start within timeout"
                raise RuntimeError(msg)

        backend = DockerBackend(container)
        console.print(f"[green]✓ Docker container ready: {backend.id}[/green]")

        # Show exposed ports if any
        if ports:
            for container_port, host_port in ports.items():
                console.print(
                    f"[dim]Port forwarding: localhost:{host_port} -> container:{container_port}[/dim]"
                )

        # Run setup script if provided
        if setup_script_path:
            _run_sandbox_setup(backend, setup_script_path)

        yield backend

    finally:
        if container and should_cleanup:
            console.print(
                f"[dim]Stopping Docker container {container.id[:12]}...[/dim]"
            )
            try:
                container.stop(timeout=10)
                container.remove()
                console.print(
                    f"[dim]✓ Docker container {container.id[:12]} terminated[/dim]"
                )
            except Exception as e:
                console.print(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


_PROVIDER_TO_WORKING_DIR = {
    "modal": "/workspace",
    "runloop": "/home/user",
    "daytona": "/home/daytona",
    "docker": "/workspace",
    "harbor": "/app",
}


# Mapping of sandbox types to their context manager factories
_SANDBOX_PROVIDERS = {
    "modal": create_modal_sandbox,
    "runloop": create_runloop_sandbox,
    "daytona": create_daytona_sandbox,
    "docker": create_docker_sandbox,
}


@contextmanager
def create_sandbox(
    provider: str,
    *,
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    ports: dict[int, int] | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to a sandbox of the specified provider.

    This is the unified interface for sandbox creation that delegates to
    the appropriate provider-specific context manager.

    Args:
        provider: Sandbox provider ("modal", "runloop", "daytona", "docker")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts
        ports: Optional port mapping for Docker sandbox {container_port: host_port}

    Yields:
        (SandboxBackend, sandbox_id)
    """
    if provider not in _SANDBOX_PROVIDERS:
        msg = (
            f"Unknown sandbox provider: {provider}. "
            f"Available providers: {', '.join(get_available_sandbox_types())}"
        )
        raise ValueError(msg)

    sandbox_provider = _SANDBOX_PROVIDERS[provider]

    # Build kwargs for sandbox provider
    sandbox_kwargs = {
        "sandbox_id": sandbox_id,
        "setup_script_path": setup_script_path,
    }

    # Only pass ports to Docker sandbox
    if provider == "docker" and ports:
        sandbox_kwargs["ports"] = ports

    with sandbox_provider(**sandbox_kwargs) as backend:
        yield backend


def get_available_sandbox_types() -> list[str]:
    """Get list of available sandbox provider types.

    Returns:
        List of sandbox type names (e.g., ["modal", "runloop", "daytona"])
    """
    return list(_SANDBOX_PROVIDERS.keys())


def get_default_working_dir(provider: str) -> str:
    """Get the default working directory for a given sandbox provider.

    Args:
        provider: Sandbox provider name ("modal", "runloop", "daytona")

    Returns:
        Default working directory path as string

    Raises:
        ValueError: If provider is unknown
    """
    if provider in _PROVIDER_TO_WORKING_DIR:
        return _PROVIDER_TO_WORKING_DIR[provider]
    msg = f"Unknown sandbox provider: {provider}"
    raise ValueError(msg)


__all__ = [
    "create_sandbox",
    "get_available_sandbox_types",
    "get_default_working_dir",
]
