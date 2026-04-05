
from novacode_cli.widgets.screens import SkillsScreen
from textual.app import App


class TestApp(App):
    def on_mount(self) -> None:
        self.notify("Launching SkillsScreen...")
        self.push_screen(SkillsScreen())


if __name__ == "__main__":
    app = TestApp()
    app.run()
