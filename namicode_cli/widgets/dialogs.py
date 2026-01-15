"""Textual dialog widgets for interactive command handling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Label, Static, ListView, ListItem, Input, Button


class SelectionDialog(Container):
    """A dialog for selecting from a list of options."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up,ctrl+p,k", "move_up", "Up", show=False),
        Binding("down,ctrl+n,j", "move_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("escape,cancel,ctrl+c", "cancel", "Cancel", show=False),
        Binding("1", "select_index", "1", show=False),
        Binding("2", "select_index", "2", show=False),
        Binding("3", "select_index", "3", show=False),
        Binding("4", "select_index", "4", show=False),
        Binding("5", "select_index", "5", show=False),
        Binding("6", "select_index", "6", show=False),
        Binding("7", "select_index", "7", show=False),
        Binding("8", "select_index", "8", show=False),
        Binding("9", "select_index", "9", show=False),
    ]

    class Selected(Message):
        """Message sent when an option is selected."""

        def __init__(self, index: int, value: str) -> None:
            """Initialize with index and value."""
            super().__init__()
            self.index = index
            self.value = value

    class Cancelled(Message):
        """Message sent when selection is cancelled."""

        def __init__(self) -> None:
            """Initialize cancelled message."""
            super().__init__()

    def __init__(
        self,
        title: str,
        items: list[tuple[str, str]],  # (label, description)
        *,
        default_index: int = 0,
        cancel_label: str = "Cancel",
        show_cancel: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the selection dialog.

        Args:
            title: Title of the dialog
            items: List of (label, description) tuples
            default_index: Index to select by default
            cancel_label: Label for cancel option
            show_cancel: Whether to show cancel option
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self._title = title
        self._items = items
        self._default_index = default_index
        self._cancel_label = cancel_label
        self._show_cancel = show_cancel
        self._list_view: ListView | None = None
        self._selected_index: int | None = None

    def compose(self) -> ComposeResult:
        """Compose the dialog layout."""
        all_items = list(self._items)

        if self._show_cancel:
            all_items.append((f"[{self._cancel_label}]", ""))

        yield Container(
            Static(self._title, classes="dialog-title"),
            ListView(
                *[
                    _SelectionItem(label, description, id=f"item-{i}")
                    for i, (label, description) in enumerate(all_items)
                ],
                id="selection-list",
            ),
            classes="dialog-content",
        )

    def on_mount(self) -> None:
        """Mount the dialog."""
        self._list_view = self.query_one("#selection-list", ListView)
        if self._default_index < len(self._list_view):
            self._list_view.focus()
            self._list_view.index = self._default_index

    def action_move_up(self) -> None:
        """Move selection up."""
        if self._list_view:
            current = self._list_view.index
            if current > 0:
                self._list_view.index = current - 1

    def action_move_down(self) -> None:
        """Move selection down."""
        if self._list_view:
            current = self._list_view.index
            if current < len(self._list_view) - 1:
                self._list_view.index = current + 1

    def action_select(self) -> None:
        """Select the current item."""
        if self._list_view:
            self._selected_index = self._list_view.index
            items = list(self._items)
            if self._show_cancel:
                items.append((self._cancel_label, ""))
            if 0 <= self._selected_index < len(items):
                label, _ = items[self._selected_index]
                self.post_message(self.Selected(self._selected_index, label))

    def action_select_index(self, index_str: str = "0") -> None:
        """Select item by number."""
        try:
            index = int(index_str) - 1  # 1-based to 0-based
            if index >= 0 and self._list_view and index < len(self._list_view):
                self._list_view.index = index
                self.action_select()
        except ValueError:
            pass

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.post_message(self.Cancelled())


class _SelectionItem(ListItem):
    """A single selection item in the list."""

    def __init__(self, label: str, description: str, **kwargs: Any) -> None:
        """Initialize the selection item."""
        content = label
        if description:
            content = f"{label}\n   {description}"
        super().__init__(Label(content, classes="selection-label"), **kwargs)
        self._label = label
        self._description = description


class InputDialog(Container):
    """A dialog for text input."""

    DEFAULT_CSS = """
    InputDialog {
        width: 60;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }

    InputDialog .dialog-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }

    InputDialog .input-prompt {
        color: $secondary;
        margin-right: 1;
    }

    InputDialog Input {
        width: 1fr;
        border: solid $surface-darken-1;
    }

    InputDialog Input:focus {
        border: solid $primary;
    }

    InputDialog .hint {
        color: $text-muted;
        margin-top: 1;
    }

    InputDialog .button-row {
        margin-top: 1;
        height: auto;
    }

    InputDialog Button {
        margin-right: 1;
    }
    """

    class Submitted(Message):
        """Message sent when input is submitted."""

        def __init__(self, value: str) -> None:
            """Initialize with submitted value."""
            super().__init__()
            self.value = value

    class Cancelled(Message):
        """Message sent when input is cancelled."""

        def __init__(self) -> None:
            """Initialize cancelled message."""
            super().__init__()

    def __init__(
        self,
        title: str,
        prompt: str,
        *,
        default: str = "",
        password: bool = False,
        hint: str = "",
        placeholder: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize the input dialog.

        Args:
            title: Title of the dialog
            prompt: Prompt text for the input
            default: Default value
            password: Whether to hide input (password mode)
            hint: Hint text shown below input
            placeholder: Placeholder text
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self._title = title
        self._prompt = prompt
        self._default = default
        self._password = password
        self._hint = hint
        self._placeholder = placeholder
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        """Compose the dialog layout."""
        yield Static(self._title, classes="dialog-title")
        yield Input(
            self._default,
            placeholder=self._placeholder,
            password=self._password,
            id="dialog-input",
        )
        if self._hint:
            yield Static(self._hint, classes="hint")

    def on_mount(self) -> None:
        """Mount the dialog."""
        self._input = self.query_one("#dialog-input", Input)
        self._input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        self.post_message(self.Submitted(event.value))

    def action_cancel(self) -> None:
        """Cancel the dialog."""
        self.post_message(self.Cancelled())


class ConfirmationDialog(Container):
    """A simple yes/no confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmationDialog {
        width: 50;
        height: auto;
        border: solid $primary;
        background: $surface;
        padding: 1;
    }

    ConfirmationDialog .dialog-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }

    ConfirmationDialog .dialog-message {
        margin-bottom: 1;
    }

    ConfirmationDialog .button-row {
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y,enter", "confirm_yes", "Yes", show=False),
        Binding("n,cancel,escape,ctrl+c", "confirm_no", "No", show=False),
    ]

    class Confirmed(Message):
        """Message sent when confirmed."""

        def __init__(self, confirmed: bool) -> None:
            """Initialize with confirmation status."""
            super().__init__()
            self.confirmed = confirmed

    def __init__(
        self,
        title: str,
        message: str,
        *,
        yes_label: str = "Yes",
        no_label: str = "No",
        default_yes: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the confirmation dialog.

        Args:
            title: Title of the dialog
            message: Message to display
            yes_label: Label for yes button
            no_label: Label for no button
            default_yes: Whether Yes is the default
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self._title = title
        self._message = message
        self._yes_label = yes_label
        self._no_label = no_label
        self._default_yes = default_yes

    def compose(self) -> ComposeResult:
        """Compose the dialog layout."""
        yield Static(self._title, classes="dialog-title")
        yield Static(self._message, classes="dialog-message")
        with Container(classes="button-row"):
            yield Button(self._yes_label, id="btn-yes", variant="primary")
            yield Button(self._no_label, id="btn-no", variant="default")

    def on_mount(self) -> None:
        """Mount the dialog."""
        if self._default_yes:
            self.query_one("#btn-yes", Button).focus()
        else:
            self.query_one("#btn-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-yes":
            self.post_message(self.Confirmed(True))
        elif event.button.id == "btn-no":
            self.post_message(self.Confirmed(False))

    def action_confirm_yes(self) -> None:
        """Confirm yes."""
        self.post_message(self.Confirmed(True))

    def action_confirm_no(self) -> None:
        """Confirm no."""
        self.post_message(self.Confirmed(False))