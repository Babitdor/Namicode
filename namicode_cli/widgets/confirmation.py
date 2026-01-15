from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmationModal(ModalScreen[bool]):
    """A generic confirmation modal."""

    CSS = """
    ConfirmationModal {
        align: center middle;
        background: $background 50%;
    }

    #confirmation-dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }

    .title {
        text-align: center;
        width: 100%;
        margin-bottom: 1;
        background: $primary;
        color: $text;
    }

    #message {
        margin: 1 0;
        width: 100%;
    }

    .buttons {
        margin-top: 1;
        align: center middle;
        width: 100%;
        height: auto;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        title: str = "Confirm Action",
        message: str = "Are you sure you want to proceed?",
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        variant: str = "primary",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.message_text = message
        self.confirm_text = confirm_text
        self.cancel_text = cancel_text
        self.confirm_variant = variant

    def compose(self) -> ComposeResult:
        with Container(id="confirmation-dialog"):
            yield Label(self.title_text, classes="title")
            yield Label(self.message_text, id="message")
            with Horizontal(classes="buttons"):
                yield Button(self.cancel_text, variant="default", id="cancel-btn")
                yield Button(
                    self.confirm_text, variant=self.confirm_variant, id="confirm-btn"
                )

    @on(Button.Pressed, "#confirm-btn")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#cancel-btn")
    def cancel(self) -> None:
        self.dismiss(False)
