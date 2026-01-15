"""Textual screens and modals for Nami Code CLI."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.screen import ModalScreen, Screen
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    DataTable,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
    Footer,
    TabbedContent,
    TabPane,
)

from namicode_cli.config.config import COLORS
from namicode_cli.config.model_manager import ModelManager
from namicode_cli.config.model_manager import MODEL_PRESETS
from namicode_cli.onboarding import SecretManager
from namicode_cli.mcp.config import MCPConfig, MCPServerConfig
from namicode_cli.mcp.presets import (
    MCP_PRESETS,
    list_presets,
    create_config_from_preset,
)
from namicode_cli.skills.load import list_skills
from namicode_cli.config.config import settings, extract_agent_description
from namicode_cli.session.session_persistence import SessionManager
from namicode_cli.config.config import SessionState
from rich.text import Text
import asyncio
from namicode_cli.server_runner.dev_server import (
    list_servers,
    stop_server,
    ProcessManager,
)
from namicode_cli.widgets.messages import ErrorMessage, SystemMessage
import webbrowser
from pathlib import Path

if TYPE_CHECKING:
    from textual.app import App


class ModelSelectionModal(ModalScreen[bool]):
    """Modal for selecting LLM provider and model."""

    CSS = """
    ModelSelectionModal {
        align: center middle;
        background: $background 50%;
    }

    #dialog {
        padding: 0 1;
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }

    .title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    .section-title {
        text-style: bold;
        margin-top: 1;
    }

    RadioSet {
        height: auto;
        max-height: 10;
        overflow-y: auto;
    }

    #api-key-container {
        display: none;
        margin-top: 1;
    }
    
    #api-key-container.visible {
        display: block;
    }

    .buttons {
        align: center middle;
        margin-top: 1;
        height: 3;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        """Initialize the model selection modal."""
        super().__init__()
        self._model_manager = ModelManager()
        self._secret_manager = SecretManager()
        self._selected_provider: str | None = None
        self._selected_model: str | None = None

        # Get current config
        current = self._model_manager.get_current_provider()
        if current:
            self._current_provider_name, self._current_model_name = current
        else:
            self._current_provider_name, self._current_model_name = None, None

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(id="dialog"):
            yield Label("Select Model Provider", classes="title")

            yield Label(
                f"Current: {self._current_provider_name} - {self._current_model_name}",
                classes="current-info",
            )

            yield Label("Provider:", classes="section-title")

            # Build provider list
            providers = []
            for provider_id, preset in MODEL_PRESETS.items():
                providers.append((provider_id, preset["name"]))

            # Find index of current provider
            current_idx = 0
            if self._current_provider_name:
                for idx, (_, name) in enumerate(providers):
                    if name == self._current_provider_name:
                        current_idx = idx
                        break

            # Create radio buttons manually to control selection
            with RadioSet(id="provider-radios"):
                for idx, (pid, name) in enumerate(providers):
                    # Default to first if current not found, or match current
                    yield RadioButton(
                        name, id=f"provider-{pid}", value=(idx == current_idx)
                    )

            yield Label("Model:", classes="section-title")
            with RadioSet(id="model-radios"):
                yield RadioButton("Select a provider first", disabled=True)

            with Vertical(id="api-key-container"):
                yield Label("API Key Required:", classes="warning")
                yield Input(
                    placeholder="Enter API Key", password=True, id="api-key-input"
                )
                yield Label("Key will be saved securely.", classes="dim")

            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        """Handle mount event."""
        # Trigger update of models based on initial selection
        if self._current_provider_name:
            # Find ID for name
            for pid, preset in MODEL_PRESETS.items():
                if preset["name"] == self._current_provider_name:
                    self._update_models(pid)
                    break
        else:
            # Default to first one
            if MODEL_PRESETS:
                first_pid = next(iter(MODEL_PRESETS))
                self._update_models(first_pid)

    @on(RadioSet.Changed, "#provider-radios")
    def on_provider_changed(self, event: RadioSet.Changed) -> None:
        """Handle provider selection change."""
        if not event.pressed.id:
            return

        provider_id = event.pressed.id.replace("provider-", "")
        self._update_models(provider_id)
        self._check_api_key(provider_id)
        self._selected_provider = provider_id

    def _update_models(self, provider_id: str) -> None:
        """Update model list based on provider."""
        model_radios = self.query_one("#model-radios", RadioSet)
        model_radios.remove_children()

        if provider_id not in MODEL_PRESETS:
            return

        preset = MODEL_PRESETS[provider_id]

        # Handle dynamic models (like Ollama)
        if provider_id == "ollama":
            from namicode_cli.config.model_manager import get_ollama_models
            models = get_ollama_models()
        else:
            models = preset.get("models", [])

        # Add radio buttons
        for model in models:
            is_current = (
                self._current_model_name == model
                and self._current_provider_name == preset["name"]
            )
            model_radios.mount(RadioButton(model, value=is_current))

        # Select default if no current match
        if not any(
            r.value for r in model_radios.children if isinstance(r, RadioButton)
        ):
            # Select default model from preset
            default_model = preset.get("default_model")
            for child in model_radios.children:
                if isinstance(child, RadioButton) and str(child.label) == default_model:
                    child.value = True
                    break

    def _check_api_key(self, provider_id: str) -> None:
        """Check if API key is needed."""
        container = self.query_one("#api-key-container")
        if provider_id not in MODEL_PRESETS:
            container.remove_class("visible")
            return

        preset = MODEL_PRESETS[provider_id]
        if not preset["requires_api_key"]:
            container.remove_class("visible")
            return

        api_key_var = preset["api_key_var"]
        api_key_name = api_key_var.lower()

        # Check if we have it
        existing_key = self._secret_manager.get_secret(api_key_name) or os.environ.get(
            api_key_var
        )

        if existing_key:
            container.remove_class("visible")
        else:
            container.add_class("visible")

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        """Cancel selection."""
        self.dismiss(False)

    @on(Button.Pressed, "#save-btn")
    def save(self) -> None:
        """Save selection."""
        # Get selected provider
        provider_radios = self.query_one("#provider-radios", RadioSet)
        if not provider_radios.pressed_button:
            return

        provider_id = provider_radios.pressed_button.id.replace("provider-", "")  # type: ignore

        # Get selected model
        model_radios = self.query_one("#model-radios", RadioSet)
        if not model_radios.pressed_button:
            return

        model_name = str(model_radios.pressed_button.label)

        # Handle API Key
        container = self.query_one("#api-key-container")
        if "visible" in container.classes:
            input_widget = self.query_one("#api-key-input", Input)
            api_key = input_widget.value.strip()

            if not api_key:
                # Basic validation: cannot save without key if required
                # In a real app show error message
                return

            preset = MODEL_PRESETS[provider_id]
            api_key_var = preset["api_key_var"]
            api_key_name = api_key_var.lower()

            # Save key
            self._secret_manager.store_secret(api_key_name, api_key)
            os.environ[api_key_var] = api_key

        # Save config
        try:
            self._model_manager.set_provider(provider_id, model_name) # type: ignore
            self.dismiss(True)
        except Exception:
            # Show error (not implemented for MVP)
            self.dismiss(False)


class InputModal(ModalScreen[str | None]):
    """Modal for requesting single line input."""

    CSS = """
    InputModal {
        align: center middle;
        background: $background 50%;
    }
    
    #input-dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }
    
    .label {
        margin-bottom: 1;
    }
    
    .buttons {
        margin-top: 1;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
    }
    """

    def __init__(self, prompt: str, password: bool = False) -> None:
        super().__init__()
        self._prompt = prompt
        self._password = password

    def compose(self) -> ComposeResult:
        with Container(id="input-dialog"):
            yield Label(self._prompt, classes="label")
            yield Input(password=self._password, id="input-field")
            with Horizontal(classes="buttons"):
                yield Button("OK", variant="primary", id="ok-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#input-field").focus()

    @on(Button.Pressed, "#ok-btn")
    def ok(self) -> None:
        value = self.query_one("#input-field", Input).value
        self.dismiss(value)

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#input-field")
    def submit(self) -> None:
        self.ok()


class MCPScreen(Screen):
    """Screen for managing MCP servers."""

    CSS = """
    MCPScreen {
        align: center middle;
    }

    .list-container {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .toolbar {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface;
    }
    
    Button {
        margin-right: 1;
    }
    
    /* Config Form */
    .form-group {
        height: auto;
        margin-bottom: 1;
    }
    
    .form-label {
        width: 15;
    }
    
    #custom-form {
        padding: 1 2;
        height: 100%;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            # Tab 1: Configured Servers
            with TabPane("Configured", id="tab-configured"):
                yield Button("Refresh", id="refresh-btn", variant="default")
                with Container(classes="list-container"):
                    yield DataTable(id="configured-table", cursor_type="row")
                with Horizontal(classes="toolbar"):
                    yield Button("Remove Selected", id="remove-btn", variant="error")

            # Tab 2: Presets
            with TabPane("Presets", id="tab-presets"):
                with Container(classes="list-container"):
                    yield DataTable(id="presets-table", cursor_type="row")
                with Horizontal(classes="toolbar"):
                    yield Button(
                        "Install Selected", id="install-btn", variant="primary"
                    )

            # Tab 3: Custom Server
            with TabPane("Add Custom", id="tab-custom"):
                with Vertical(id="custom-form"):
                    yield Label("Add Custom MCP Server", classes="title")

                    yield Label("Name:")
                    yield Input(placeholder="my-server", id="custom-name")

                    yield Label("Transport:")
                    with RadioSet(id="custom-transport"):
                        yield RadioButton("stdio", value=True)
                        yield RadioButton("http")

                    yield Label("Command (stdio) / URL (http):")
                    yield Input(placeholder="npx or https://...", id="custom-command")

                    yield Label("Arguments (stdio only):")
                    yield Input(
                        placeholder="-y @org/package arg1 arg2", id="custom-args"
                    )

                    yield Label("Environment Variables (KEY=VAL):")
                    yield Input(placeholder="API_KEY=123, DEBUG=true", id="custom-env")

                    yield Button("Add Server", id="add-custom-btn", variant="primary")

        # Back button - OUTSIDE TabbedContent so always visible
        with Horizontal(classes="toolbar"):
            yield Button("← Back to Chat", id="back-btn", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize tables."""
        # Use call_after_refresh to ensure DOM is ready
        self.call_after_refresh(self._refresh_configured)
        self.call_after_refresh(self._refresh_presets)

    def _refresh_configured(self) -> None:
        """Refresh configured servers table."""
        self.run_worker(self._fetch_configured_worker())

    async def _fetch_configured_worker(self) -> None:
        """Fetch configured servers in background."""
        import asyncio
        from namicode_cli.mcp.config import MCPConfig

        def get_data():
            config = MCPConfig()
            return config.list_servers()

        servers = await asyncio.to_thread(get_data)

        # After to_thread, we're back on the event loop - update UI directly
        try:
            table = self.query_one("#configured-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Name", "Transport", "Description")
            for name, cfg in servers.items():
                desc = getattr(cfg, "description", "") or ""
                table.add_row(name, cfg.transport, desc, key=name)
        except NoMatches:
            pass

    def _refresh_presets(self) -> None:
        """Refresh presets table."""
        try:
            table = self.query_one("#presets-table", DataTable)
        except NoMatches:
            return
        table.clear(columns=True)
        table.add_columns("ID", "Name", "Description")

        presets = list_presets()
        for pid, p in presets.items():
            table.add_row(pid, p["name"], p["description"], key=pid)

    @on(Button.Pressed, "#refresh-btn")
    def handle_refresh(self) -> None:
        self._refresh_configured()

    @on(Button.Pressed, "#remove-btn")
    def on_remove(self) -> None:
        """Remove selected server."""
        try:
            table = self.query_one("#configured-table", DataTable)
        except NoMatches:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if not row_key:
                return

            server_name = row_key.value
            config = MCPConfig()
            if config.remove_server(server_name):
                self.notify(f"Removed server: {server_name}")
                self._refresh_configured()
            else:
                self.notify("Failed to remove server", severity="error")
        except Exception:
            self.notify("Select a server to remove", severity="warning")

    @on(Button.Pressed, "#install-btn")
    async def on_install(self) -> None:
        """Install selected preset."""
        try:
            table = self.query_one("#presets-table", DataTable)
        except NoMatches:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if not row_key:
                return

            preset_id = row_key.value
            preset = MCP_PRESETS.get(preset_id)
            if not preset:
                return

            # Collect inputs
            user_inputs = {}

            # Helper to prompt
            async def get_input(prompt: str, key: str, password: bool = False):
                val = await self.app.push_screen_wait(InputModal(prompt, password))
                if val:
                    user_inputs[key] = val
                return val

            # Primary prompt
            if "setup_prompt" in preset:
                is_pass = "key" in preset["setup_key"] or "token" in preset["setup_key"]
                if not await get_input(
                    preset["setup_prompt"], preset["setup_key"], is_pass
                ):
                    self.notify("Installation cancelled")
                    return

            # Secondary prompt
            if "setup_secondary_prompt" in preset:
                is_pass = (
                    "key" in preset["setup_secondary_key"]
                    or "token" in preset["setup_secondary_key"]
                )
                if not await get_input(
                    preset["setup_secondary_prompt"],
                    preset["setup_secondary_key"],
                    is_pass,
                ):
                    self.notify("Installation cancelled")
                    return

            # Create and save
            try:
                config_obj = create_config_from_preset(preset_id, user_inputs)
                if config_obj:
                    mcp_config = MCPConfig()
                    mcp_config.add_server(preset_id, config_obj)
                    self.notify(f"Installed MCP preset: {preset['name']}")
                    self._refresh_configured()

                    # Switch to configured tab
                    self.query_one(TabbedContent).active = "tab-configured"
            except Exception as e:
                self.notify(f"Error installing preset: {e}", severity="error")

        except Exception:
            self.notify("Select a preset to install", severity="warning")

    @on(Button.Pressed, "#add-custom-btn")
    def on_add_custom(self) -> None:
        """Add custom server."""
        name = self.query_one("#custom-name", Input).value.strip()
        transport_radio = self.query_one("#custom-transport", RadioSet)
        transport = "stdio" if transport_radio.pressed_button.label == "stdio" else "http"  # type: ignore
        command_url = self.query_one("#custom-command", Input).value.strip()
        args_str = self.query_one("#custom-args", Input).value.strip()
        env_str = self.query_one("#custom-env", Input).value.strip()

        if not name or not command_url:
            self.notify("Name and Command/URL are required", severity="error")
            return

        try:
            env = {}
            if env_str:
                for pair in env_str.split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        env[k.strip()] = v.strip()

            if transport == "stdio":
                config = MCPServerConfig(
                    transport="stdio",
                    command=command_url,
                    args=args_str.split() if args_str else [],
                    env=env,
                )
            else:
                config = MCPServerConfig(transport="http", url=command_url)

            mcp_config = MCPConfig()
            mcp_config.add_server(name, config)
            self.notify(f"Added custom server: {name}")

            # Reset form
            self.query_one("#custom-name", Input).value = ""
            self.query_one("#custom-command", Input).value = ""
            self.query_one("#custom-args", Input).value = ""
            self.query_one("#custom-env", Input).value = ""

            self._refresh_configured()
            self.query_one(TabbedContent).active = "tab-configured"

        except Exception as e:
            self.notify(f"Error adding server: {e}", severity="error")

    @on(Button.Pressed, "#back-btn")
    def handle_back(self) -> None:
        """Return to chat."""
        self.app.pop_screen()


class SkillCreateModal(ModalScreen[dict | None]):
    """Modal for creating a new skill."""

    CSS = """
    SkillCreateModal {
        align: center middle;
        background: $background 50%;
    }
    
    #skill-dialog {
        padding: 1 2;
        width: 70;
        height: auto;
        border: thick $primary;
        background: $surface;
    }
    
    .label {
        margin-top: 1;
        margin-bottom: 0;
    }

    .buttons {
        margin-top: 2;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="skill-dialog"):
            yield Label("Create New Skill", classes="title")

            yield Label("Skill Name:", classes="label")
            yield Input(placeholder="my-cool-skill", id="skill-name")

            yield Label("Description:", classes="label")
            yield Input(placeholder="What does this skill do?", id="skill-desc")

            yield Label("Scope:", classes="label")
            with RadioSet(id="skill-scope"):
                yield RadioButton(
                    "Project (current project only)", value=True, id="scope-project"
                )
                yield RadioButton("Global (all projects)", id="scope-global")

            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#skill-name").focus()

        # Check if project scope is available
        if not settings.project_root:
            self.query_one("#scope-project", RadioButton).disabled = True
            self.query_one("#scope-global", RadioButton).value = True

    @on(Button.Pressed, "#create-btn")
    def create(self) -> None:
        name = self.query_one("#skill-name", Input).value.strip()
        desc = self.query_one("#skill-desc", Input).value.strip()
        scope_radio = self.query_one("#skill-scope", RadioSet)
        is_project = scope_radio.pressed_button.id == "scope-project"  # type: ignore

        if not name or not desc:
            self.notify("Name and Description are required", severity="error")
            return

        # Validate name using shared logic
        from namicode_cli.skills.commands import _validate_name
        is_valid, error_msg = _validate_name(name)
        if not is_valid:
            self.notify(f"Invalid name: {error_msg}", severity="error")
            return

        self.dismiss(
            {
                "name": name,
                "description": desc,
                "scope": "project" if is_project else "global",
            }
        )

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.dismiss(None)


class SkillsScreen(Screen):
    """Screen for managing skills."""

    def __init__(self, assistant_id: str = "nami-agent", **kwargs) -> None:
        super().__init__(**kwargs)
        self.assistant_id = assistant_id
        self._skill_paths: dict[str, str] = {}
        self._skill_scopes: dict[str, str] = {}

    CSS = """
    SkillsScreen {
        align: center middle;
    }

    .list-container {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .toolbar {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface;
    }
    
    Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Skills Management", classes="title"),
            Container(
                DataTable(id="skills-table", cursor_type="row"),
                classes="list-container",
            ),
            Horizontal(
                Button("Create New Skill", id="create-btn", variant="primary"),
                Button("Delete Skill", id="delete-btn", variant="error"),
                Button("Refresh", id="refresh-btn", variant="default"),
                Button("← Back to Chat", id="back-btn", variant="default"),
                classes="toolbar",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_list)

    def _refresh_list(self) -> None:
        """Refresh skill list."""
        self.run_worker(self._fetch_skills_worker())

    async def _fetch_skills_worker(self) -> None:
        """Fetch skills in background."""
        # Move ALL work inside to_thread
        def fetch_all_skills():
            project_skills_dirs = settings.get_project_skills_dirs()
            user_skills_dir = settings.get_user_skills_dir(self.assistant_id)
            skills = list_skills(
                user_skills_dir=user_skills_dir, project_skills_dirs=project_skills_dirs
            )
            # Sort: project first, then by name
            skills.sort(key=lambda x: (0 if x['source'] == "project" else 1, x['name']))
            return skills

        skills = await asyncio.to_thread(fetch_all_skills)

        # After to_thread, we're back on the event loop - update UI directly
        try:
            table = self.query_one("#skills-table", DataTable)
            table.clear() # Only clear rows, keep columns

            for skill in skills:
                # Skill name with primary color
                name_text = Text(skill['name'], style="bold #ef4444")
                
                # Scope with specific colors matching CLI
                scope_style = "bold green" if skill['source'] == "project" else "bold cyan"
                scope_text = Text("Project" if skill['source'] == "project" else "Global", style=scope_style)
                
                # Description and Path
                desc_text = Text(skill['description'], style="dim")
                path_text = Text(skill['path'], style="dim italic")

                table.add_row(
                    name_text,
                    scope_text,
                    desc_text,
                    path_text,
                    key=skill["name"],
                )
            
            # Store paths for deletion
            self._skill_paths = {s['name']: s['path'] for s in skills}
            self._skill_scopes = {s['name']: "Global" if s['source'] == 'user' else "Project" for s in skills}
            
        except NoMatches:
            pass

    @on(Button.Pressed, "#refresh-btn")
    def handle_refresh(self) -> None:
        self._refresh_list()

    @on(Button.Pressed, "#delete-btn")
    async def delete_skill(self) -> None:
        """Delete selected skill."""
        table = self.query_one("#skills-table", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            skill_name = row_key.value
            
            if not skill_name:
                return

            path = self._skill_paths.get(skill_name)
            scope = self._skill_scopes.get(skill_name, "Global")
            
            if not path:
                self.notify("Skill path not found", severity="error")
                return

            # Confirm deletion
            from .confirmation import ConfirmationModal
            result = await self.app.push_screen_wait(
                ConfirmationModal(
                    title="Delete Skill",
                    message=f"Are you sure you want to delete the {scope.lower()} skill '{skill_name}'?\n\nThis cannot be undone and will delete all files in:\n{path}",
                    confirm_text="Delete",
                    variant="error"
                )
            )

            if result:
                import shutil
                import asyncio
                import os
                
                try:
                    # In skills, the path is to SKILL.md, but we want to delete the directory
                    import pathlib
                    skill_dir = pathlib.Path(path).parent
                    
                    await asyncio.to_thread(shutil.rmtree, str(skill_dir))
                    self.notify(f"Skill '{skill_name}' deleted")
                    self._refresh_list()
                except Exception as e:
                    self.notify(f"Error deleting skill: {e}", severity="error")
                    
        except NoMatches:
            self.notify("No skill selected", severity="warning")
        except Exception as e:
            self.notify(f"Selection error: {e}", severity="error")

    @on(Button.Pressed, "#back-btn")
    def handle_back(self) -> None:
        """Return to chat."""
        self.app.pop_screen()

    @on(Button.Pressed, "#create-btn")
    async def create_skill(self) -> None:
        """Handle create skill action."""
        result = await self.app.push_screen_wait(SkillCreateModal())
        if not result:
            return

        name = result["name"]
        desc = result["description"]
        scope = result["scope"]

        # Start creating in a worker
        self.notify(f"Creating skill '{name}'... (this may take a moment)")
        self.run_worker(self._create_skill_worker(name, desc, scope))

    async def _create_skill_worker(self, name: str, desc: str, scope: str) -> None:
        """Worker to generate skill using LLM."""
        try:
            # We need to import the generation logic
            # Since _generate_skill_with_scripts is not async, we wrap it or just run it in thread
            # Actually run_worker runs in a thread by default for sync functions?
            # If function is async, it runs on event loop. If sync, usually blocks unless using specialized worker.
            # Textual workers for non-async functions run in thread if `thread=True` (default for `work` decorator).
            # But `run_worker` takes an awaitable or callable.

            # Let's import inside worker to avoid circular initial imports if any
            from namicode_cli.skills.commands import _generate_skill_with_scripts
            from pathlib import Path

            # Determine target directory
            if scope == "project":
                target_dir = settings.ensure_project_skills_dir()
            else:
                target_dir = settings.ensure_user_skills_dir(self.assistant_id)

            skill_dir = target_dir / name
            if skill_dir.exists():
                self.post_message(ErrorMessage(f"Skill '{name}' already exists"))
                return

            # Run generation (this is blocking, so we should run it in an executor if we are in async worker)
            # Or define this worker as non-async and let Textual handle threading?
            # Textual's run_worker expects an awaitable usually.
            # To run blocking code, we can use asyncio.to_thread

            import asyncio

            result = await asyncio.to_thread(_generate_skill_with_scripts, name, desc)

            content, scripts = result

            if not content:
                self.post_message(ErrorMessage("Failed to generate skill content"))
                return

            # Save files
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

            for script in scripts:
                script_path = skill_dir / script["filename"]
                script_path.write_text(script["content"], encoding="utf-8")
                # Make executable if bash/python
                import os

                os.chmod(script_path, 0o755)

            self.post_message(SystemMessage(f"Skill '{name}' created successfully!"))

            # Refresh list - we are in an async worker on the main thread
            self._refresh_list()

        except Exception as e:
            self.post_message(ErrorMessage(f"Error creating skill: {e}"))

    def post_message(self, message: Any) -> None: # type: ignore
        msg_text = str(message)
        # If we are in the main thread, we can call notify directly
        # If in a thread, we should use call_from_thread.
        # Screen.notify is thread-safe in recent Textual? Let's check.
        # Actually, self.app.notify is safer.
        self.app.notify(msg_text, severity="error" if isinstance(message, ErrorMessage) else "info") # type: ignore


class AgentCreateModal(ModalScreen[dict | None]):
    """Modal for creating a new agent."""

    CSS = """
    AgentCreateModal {
        align: center middle;
        background: $background 50%;
    }
    
    #agent-dialog {
        padding: 1 2;
        width: 70;
        height: auto;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        overflow-y: auto;
    }
    
    .label {
        margin-top: 1;
        margin-bottom: 0;
    }

    .buttons {
        margin-top: 2;
        align: center middle;
        height: auto;
    }
    
    Button {
        margin: 0 1;
    }
    """

    COLOR_OPTIONS = [
        ("#ef4444", "Red"),
        ("#f97316", "Orange"),
        ("#f59e0b", "Amber"),
        ("#fbbf24", "Yellow"),
        ("#22c55e", "Green"),
        ("#14b8a6", "Teal"),
        ("#0ea5e9", "Sky Blue"),
        ("#3b82f6", "Blue"),
        ("#8b5cf6", "Violet"),
        ("#a855f7", "Purple"),
        ("#ec4899", "Pink"),
        ("#6b7280", "Gray"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="agent-dialog"):
            yield Label("Create New Agent", classes="title")

            yield Label("Agent Name:", classes="label")
            yield Input(placeholder="code-reviewer", id="agent-name")

            yield Label("Description (Specialization):", classes="label")
            yield Input(
                placeholder="Reviews code for security and performance...",
                id="agent-desc",
            )

            yield Label("Scope:", classes="label")
            with RadioSet(id="agent-scope"):
                yield RadioButton(
                    "Global (available everywhere)", value=True, id="scope-global"
                )
                yield RadioButton("Project (this project only)", id="scope-project")

            yield Label("Color:", classes="label")
            # Simple color selection - maybe a horizontal list of buttons or a select?
            # For now, let's use a Select if available or just RadioSet
            from textual.widgets import Select

            options = [(f"{name} {code}", code) for code, name in self.COLOR_OPTIONS]
            yield Select(options, value=options[6][1], id="agent-color")

            with Horizontal(classes="buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one("#agent-name").focus()

        # Check if project scope is available
        if not settings.project_root:
            self.query_one("#scope-project", RadioButton).disabled = True

    @on(Button.Pressed, "#create-btn")
    def create(self) -> None:
        name = self.query_one("#agent-name", Input).value.strip()
        desc = self.query_one("#agent-desc", Input).value.strip()

        # Validate name
        if not settings._is_valid_agent_name(name):
            self.notify(f"Invalid name: {name}", severity="error")
            return

        if not desc:
            self.notify("Description is required", severity="error")
            return

        scope_radio = self.query_one("#agent-scope", RadioSet)
        is_project = scope_radio.pressed_button.id == "scope-project"  # type: ignore

        from textual.widgets import Select

        color = self.query_one("#agent-color", Select).value

        self.dismiss(
            {
                "name": name,
                "description": desc,
                "scope": "project" if is_project else "global",
                "color": color,
            }
        )

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.dismiss(None)


class AgentsScreen(Screen):
    """Screen for managing agents."""

    def __init__(self, assistant_id: str = "nami-agent", **kwargs) -> None:
        super().__init__(**kwargs)
        self.assistant_id = assistant_id
        self._agent_paths: dict[str, str] = {}
        self._agent_scopes: dict[str, str] = {}

    CSS = """
    AgentsScreen {
        align: center middle;
    }

    .list-container {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .toolbar {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface;
    }
    
    Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Agent Management", classes="title"),
            Container(
                DataTable(id="agents-table", cursor_type="row"),
                classes="list-container",
            ),
            Horizontal(
                Button("Create New Agent", id="create-btn", variant="primary"),
                Button("Delete Agent", id="delete-btn", variant="error"),
                Button("Refresh", id="refresh-btn", variant="default"),
                Button("← Back to Chat", id="back-btn", variant="default"),
                classes="toolbar",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Called when screen is mounted."""
        # Initialize table columns
        try:
            table = self.query_one("#agents-table", DataTable)
            table.add_columns("Name", "Scope", "Shadowed", "Description")
        except NoMatches:
            pass
            
        # Schedule refresh after DOM is fully composed to avoid NoMatches error
        self.call_after_refresh(self._refresh_list)

    def _refresh_list(self) -> None:
        """Refresh agent list."""
        self.run_worker(self._fetch_agents_worker())

    async def _fetch_agents_worker(self) -> None:
        """Fetch agents in background."""
        # Move ALL work inside to_thread
        def fetch_all_agents():
            agents = settings.get_all_agents()
            
            # Identify which are shadowed
            project_names = {name for name, _, scope in agents if scope == "project"}
            
            results = []
            for name, path_obj, scope in agents:
                try:
                    desc = extract_agent_description(Path(path_obj)) or ""
                except Exception:
                    desc = ""
                
                shadowed = scope == "global" and name in project_names
                results.append({
                    "name": name,
                    "scope": scope,
                    "description": desc,
                    "shadowed": shadowed,
                    "path": str(path_obj)
                })
            
            # Sort: project first, then by name
            results.sort(key=lambda x: (0 if x['scope'] == "project" else 1, x['name']))
            return results

        processed_agents = await asyncio.to_thread(fetch_all_agents)

        # After to_thread, we're back on the event loop - update UI directly
        try:
            table = self.query_one("#agents-table", DataTable)
            table.clear() # Only clear rows, keep columns

            for agent in processed_agents:
                # Agent name with @ prefix and primary color
                name_text = Text(f"@{agent['name']}", style="bold #ef4444")
                
                # Scope with specific colors matching CLI
                scope_style = "bold green" if agent['scope'] == "project" else "bold cyan"
                scope_text = Text(agent['scope'].title(), style=scope_style)
                
                # Shadowed status
                shadow_text = Text("Yes", style="yellow") if agent['shadowed'] else Text("No", style="dim")
                
                # Description
                desc_text = Text(agent['description'], style="dim")

                table.add_row(
                    name_text, 
                    scope_text, 
                    shadow_text, 
                    desc_text, 
                    key=agent['name']
                )
            
            # Store paths for deletion
            self._agent_paths = {a['name']: a['path'] for a in processed_agents}
            self._agent_scopes = {a['name']: a['scope'].title() for a in processed_agents}
            
        except NoMatches:
            pass

    @on(Button.Pressed, "#refresh-btn")
    def handle_refresh(self) -> None:
        self._refresh_list()

    @on(Button.Pressed, "#back-btn")
    def handle_back(self) -> None:
        """Return to chat."""
        self.app.pop_screen()

    @on(Button.Pressed, "#delete-btn")
    async def delete_agent(self) -> None:
        """Delete selected agent."""
        table = self.query_one("#agents-table", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            agent_name = row_key.value # This is the name we used as key
            
            if not agent_name:
                return

            path = self._agent_paths.get(agent_name)
            scope = self._agent_scopes.get(agent_name, "Global")
            
            if not path:
                self.notify("Agent path not found", severity="error")
                return

            # Confirm deletion
            from .confirmation import ConfirmationModal
            result = await self.app.push_screen_wait(
                ConfirmationModal(
                    title="Delete Agent",
                    message=f"Are you sure you want to delete the {scope.lower()} agent '@{agent_name}'?\n\nThis cannot be undone and will delete all files in:\n{path}",
                    confirm_text="Delete",
                    variant="error"
                )
            )

            if result:
                import shutil
                import asyncio
                
                try:
                    await asyncio.to_thread(shutil.rmtree, path)
                    self.notify(f"Agent '@{agent_name}' deleted")
                    self._refresh_list()
                except Exception as e:
                    self.notify(f"Error deleting agent: {e}", severity="error")
                    
        except NoMatches:
            self.notify("No agent selected", severity="warning")
        except Exception as e:
            self.notify(f"Selection error: {e}", severity="error")

    @on(Button.Pressed, "#create-btn")
    async def create_agent(self) -> None:
        """Handle create agent action."""
        result = await self.app.push_screen_wait(AgentCreateModal())
        if not result:
            return

        name = result["name"]
        desc = result["description"]
        scope = result["scope"]
        color = result["color"]

        self.notify(f"Generating agent '{name}'... (this takes 10+ seconds)")
        self.run_worker(self._create_agent_worker(name, desc, scope, color))

    async def _create_agent_worker(
        self, name: str, desc: str, scope: str, color: str
    ) -> None:
        """Worker to generate agent."""
        try:
            from namicode_cli.agents.commands import _generate_agent_system_prompt

            # Determine dir
            if scope == "project":
                target_dir = settings.ensure_project_agents_dir()
                # Handle error if None
                if not target_dir:
                    self.post_message(ErrorMessage("Project directory not available"))
                    return
            else:
                target_dir = settings.get_agents_root_dir()

            agent_dir = target_dir / name
            if agent_dir.exists():
                self.post_message(ErrorMessage(f"Agent '{name}' already exists"))
                return

            # Generate prompt
            import asyncio

            system_prompt = await _generate_agent_system_prompt(name, desc)

            if not system_prompt:
                self.post_message(ErrorMessage("Failed to generate system prompt"))
                return

            # Create content
            content = (
                f"---\ncolor: {color}\ndescription: {desc}\n---\n\n{system_prompt}"
            )

            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "agent.md").write_text(content, encoding="utf-8")

            self.post_message(SystemMessage(f"Agent '{name}' created successfully!"))
            self._refresh_list()

        except Exception as e:
            self.post_message(ErrorMessage(f"Error creating agent: {e}"))

    def post_message(self, message: Any) -> None:
        msg_text = str(message)
        self.app.notify(msg_text, severity="error" if hasattr(message, "type") and message.type == "error" else "info")


class SessionsScreen(Screen):
    """Screen for managing saved sessions."""

    CSS = """
    SessionsScreen {
        align: center middle;
    }

    .list-container {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .toolbar {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface;
    }
    
    Button {
        margin-right: 1;
    }
    """

    def __init__(self, session_state: SessionState) -> None:
        super().__init__()
        self._session_state = session_state
        self._session_manager = SessionManager()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Session Management", classes="title"),
            Container(
                DataTable(id="sessions-table", cursor_type="row"),
                classes="list-container",
            ),
            Horizontal(
                Button("Refresh", id="refresh-btn", variant="default"),
                Button("Delete Selected", id="delete-btn", variant="error"),
                Button("← Back to Chat", id="back-btn", variant="default"),
                classes="toolbar",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_list)

    def _refresh_list(self) -> None:
        """Refresh sessions list."""
        self.run_worker(self._fetch_sessions_worker())

    async def _fetch_sessions_worker(self) -> None:
        """Fetch sessions in background."""
        import asyncio

        # limit=20
        sessions = await asyncio.to_thread(self._session_manager.list_sessions, limit=20)

        # After to_thread, we're back on the event loop - update UI directly
        try:
            table = self.query_one("#sessions-table", DataTable)
            table.clear(columns=True)
            table.add_columns("ID", "Project", "Model", "Messages", "Last Active")

            for meta in sessions:
                project_name = (
                    Path(meta.project_root).name if meta.project_root else "-"
                )
                model = meta.model_name or "?"
                age = str(meta.last_active)
                is_current = self._session_state.session_id == meta.session_id
                id_display = (
                    f"{meta.session_id[:8]}{' (current)' if is_current else ''}"
                )

                table.add_row(
                    id_display,
                    project_name,
                    model,
                    str(meta.message_count),
                    age,
                    key=meta.session_id,
                )
        except NoMatches:
            pass

    @on(Button.Pressed, "#refresh-btn")
    def handle_refresh(self) -> None:
        self._refresh_list()

    @on(Button.Pressed, "#back-btn")
    def handle_back(self) -> None:
        """Return to chat."""
        self.app.pop_screen()

    @on(Button.Pressed, "#delete-btn")
    def delete_session(self) -> None:
        """Delete selected session."""
        try:
            table = self.query_one("#sessions-table", DataTable)
        except NoMatches:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if not row_key:
                return

            session_id = row_key.value
            if self._session_manager.delete_session(session_id):
                self.notify(f"Deleted session: {session_id[:8]}")
                self._refresh_list()
            else:
                self.notify("Failed to delete session", severity="error")
        except Exception:
            self.notify("Select a session to delete", severity="warning")


class ServersScreen(Screen):
    """Screen for managing dev servers."""

    CSS = """
    ServersScreen {
        align: center middle;
    }

    .list-container {
        height: 1fr;
        border: solid $secondary;
        margin: 1 0;
    }
    
    .toolbar {
        height: auto;
        dock: bottom;
        padding: 1;
        background: $surface;
    }
    
    Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Dev Server Management", classes="title"),
            Container(
                DataTable(id="servers-table", cursor_type="row"),
                classes="list-container",
            ),
            Horizontal(
                Button("Open in Browser", id="open-btn", variant="primary"),
                Button("Stop Selected", id="stop-btn", variant="error"),
                Button("Stop ALL", id="stop-all-btn", variant="error"),
                Button("Refresh", id="refresh-btn", variant="default"),
                Button("← Back to Chat", id="back-btn", variant="default"),
                classes="toolbar",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_list)

    def _refresh_list(self) -> None:
        """Refresh server list."""
        self.run_worker(self._fetch_servers_worker())

    async def _fetch_servers_worker(self) -> None:
        """Fetch servers in background."""
        import asyncio

        servers = await asyncio.to_thread(list_servers)

        # After to_thread, we're back on the event loop - update UI directly
        try:
            table = self.query_one("#servers-table", DataTable)
            table.clear(columns=True)
            table.add_columns("PID", "Name", "URL", "Status", "Command")

            for server in servers:
                table.add_row(
                    str(server.pid),
                    server.name,
                    server.url,
                    server.status.value,
                    server.command,
                    key=str(server.pid),
                )
        except NoMatches:
            pass

    @on(Button.Pressed, "#refresh-btn")
    def handle_refresh(self) -> None:
        self._refresh_list()

    @on(Button.Pressed, "#back-btn")
    def handle_back(self) -> None:
        """Return to chat."""
        self.app.pop_screen()

    @on(Button.Pressed, "#open-btn")
    def open_browser(self) -> None:
        """Open selected server in browser."""
        try:
            table = self.query_one("#servers-table", DataTable)
        except NoMatches:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if not row_key:
                return

            # Find server by PID
            pid = int(row_key.value)
            servers = list_servers()
            server = next((s for s in servers if s.pid == pid), None)

            if server and server.url:
                webbrowser.open(server.url)
                self.notify(f"Opened {server.url}")
            else:
                self.notify("Server not found or no URL", severity="warning")
        except Exception:
            self.notify("Select a server to open", severity="warning")

    @on(Button.Pressed, "#stop-btn")
    async def stop_server(self) -> None:
        """Stop selected server."""
        try:
            table = self.query_one("#servers-table", DataTable)
        except NoMatches:
            return
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            if not row_key:
                return

            pid = int(row_key.value)
            success = await stop_server(pid)
            if success:
                self.notify(f"Stopped server PID {pid}")
                self._refresh_list()
            else:
                self.notify(f"Failed to stop server PID {pid}", severity="error")
        except Exception:
            self.notify("Select a server to stop", severity="warning")

    @on(Button.Pressed, "#stop-all-btn")
    async def stop_all(self) -> None:
        """Stop all servers."""
        manager = ProcessManager.get_instance()
        count = await manager.stop_all()
        self.notify(f"Stopped {count} servers")
        self._refresh_list()
