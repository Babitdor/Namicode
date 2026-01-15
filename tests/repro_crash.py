from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from namicode_cli.widgets.screens import SkillsScreen, AgentsScreen, MCPScreen
from namicode_cli.app import TextualSessionState
import asyncio

class TestApp(App):
    def on_mount(self) -> None:
        self.notify("Launching SkillsScreen...")
        self.push_screen(SkillsScreen())

if __name__ == "__main__":
    app = TestApp()
    app.run()
