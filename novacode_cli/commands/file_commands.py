"""Handlers for file-related commands: /files, /images, /restore."""

from datetime import datetime
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from novacode_cli.config.config import COLORS, console
from novacode_cli.recovery import REASON_LABELS, get_recovery_manager


async def handle_files_command() -> bool:
    """Handle /files command to show file operation summary for the session.

    Returns:
        True (always handled)
    """
    from novacode_cli.tracking.file_tracker import get_session_tracker

    console.print()

    tracker = get_session_tracker()

    # Header
    header = Text()
    header.append("📁 ", style="bold")
    header.append("Session File Operations", style=f"bold {COLORS['primary']}")

    console.print(Panel(header, border_style=COLORS["primary"]))
    console.print()

    # Stats summary
    console.print("[bold]Statistics:[/bold]")
    console.print(f"  • Files read: [cyan]{len(tracker.files_read)}[/cyan]")
    console.print(f"  • Files modified: [cyan]{len(tracker.files_written)}[/cyan]")
    console.print(f"  • Total read operations: [dim]{tracker.total_reads}[/dim]")
    console.print(f"  • Total write operations: [dim]{tracker.total_writes}[/dim]")
    if tracker.rejected_edits > 0:
        console.print(
            f"  • [red]Rejected edits (unread files): {tracker.rejected_edits}[/red]"
        )
    console.print()

    # Files read
    if tracker.files_read:
        console.print("[bold]Files Read:[/bold]")
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("File", style="cyan")
        table.add_column("Lines", justify="right")
        table.add_column("Read At", style="dim")

        for path in tracker.read_order[-15:]:  # Show last 15
            record = tracker.files_read[path]
            # Shorten path for display
            display_path = path
            if len(display_path) > 60:
                display_path = "..." + display_path[-57:]
            time_str = (
                record.read_at.split("T")[1][:8]
                if "T" in record.read_at
                else record.read_at
            )
            table.add_row(display_path, str(record.line_count), time_str)

        console.print(table)
        if len(tracker.read_order) > 15:
            console.print(
                f"  [dim]... and {len(tracker.read_order) - 15} more files[/dim]"
            )
        console.print()
    else:
        console.print("[dim]No files read in this session.[/dim]")
        console.print()

    # Files modified
    if tracker.files_written:
        console.print("[bold]Files Modified:[/bold]")
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("File", style="yellow")
        table.add_column("Operations", justify="center")
        table.add_column("Last Modified", style="dim")

        for path in tracker.write_order[-15:]:  # Show last 15
            records = tracker.files_written[path]
            # Shorten path for display
            display_path = path
            if len(display_path) > 60:
                display_path = "..." + display_path[-57:]
            ops = ", ".join(r.operation for r in records[-3:])  # Last 3 ops
            if len(records) > 3:
                ops = f"({len(records)}x) " + ops
            last_time = records[-1].written_at
            time_str = last_time.split("T")[1][:8] if "T" in last_time else last_time
            table.add_row(display_path, ops, time_str)

        console.print(table)
        if len(tracker.write_order) > 15:
            console.print(
                f"  [dim]... and {len(tracker.write_order) - 15} more files[/dim]"
            )
        console.print()
    else:
        console.print("[dim]No files modified in this session.[/dim]")
        console.print()

    # Context note
    console.print(
        "[dim]Note: The system enforces read-before-edit to prevent hallucinations.[/dim]"
    )
    console.print("[dim]Files must be read before they can be edited.[/dim]")
    console.print()

    return True


async def handle_images_command(args: str | None, image_tracker) -> bool:
    """Handle /images command to manage images in the conversation.

    Usage:
        /images          - List all images in the conversation
        /images list     - List all images
        /images remove <id> - Remove an image by ID (e.g., /images remove image-1)
        /images clear    - Clear all images

    Args:
        args: Optional arguments (list, remove <id>, clear).
        image_tracker: The ImageTracker instance.

    Returns:
        True (always handled).
    """
    console.print()

    if image_tracker is None:
        console.print("[yellow]Image tracking not available.[/yellow]")
        console.print()
        return True

    # Parse subcommand
    if args is None or args.strip() == "" or args.strip().lower() == "list":
        # List all images
        images = image_tracker.list_images()

        if not images:
            console.print("[dim]No images in the current conversation.[/dim]")
            console.print()
            console.print(
                "[dim]Tip: Paste an image with Ctrl+V or use @path/to/image.png[/dim]"
            )
            console.print()
            return True

        # Header
        header = Text()
        header.append("🖼️ ", style="bold")
        header.append("Images in Conversation", style=f"bold {COLORS['primary']}")

        console.print(Panel(header, border_style=COLORS["primary"]))
        console.print()

        # Create table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("ID", style="cyan")
        table.add_column("Format", style="dim")
        table.add_column("Size", justify="right")
        table.add_column("Placeholder")

        for img in images:
            size_str = f"{img['size_kb']:.1f} KB"
            table.add_row(
                img["id"],
                img["format"].upper(),
                size_str,
                img["placeholder"],
            )

        console.print(table)
        console.print()
        console.print(f"[dim]Total: {len(images)} image(s)[/dim]")
        console.print()
        console.print("[dim]Use /images remove <id> to remove an image[/dim]")
        console.print("[dim]Use /images clear to remove all images[/dim]")
        console.print()
        return True

    arg_parts = args.strip().split(maxsplit=1)
    subcmd = arg_parts[0].lower()

    if subcmd == "remove":
        if len(arg_parts) < 2:
            console.print("[red]Usage: /images remove <id>[/red]")
            console.print("[dim]Example: /images remove image-1[/dim]")
            console.print()
            return True

        image_id = arg_parts[1].strip()

        # Normalize ID format (allow "1" or "image-1")
        if not image_id.startswith("image-"):
            image_id = f"image-{image_id}"

        if image_tracker.remove_image(image_id):
            console.print(f"[green]Removed {image_id}[/green]")
        else:
            console.print(f"[red]Image not found: {image_id}[/red]")
            # Show available images
            images = image_tracker.list_images()
            if images:
                available = ", ".join(img["id"] for img in images)
                console.print(f"[dim]Available images: {available}[/dim]")
        console.print()
        return True

    if subcmd == "clear":
        count = image_tracker.count
        if count == 0:
            console.print("[dim]No images to clear.[/dim]")
        else:
            image_tracker.clear()
            console.print(f"[green]Cleared {count} image(s) from conversation[/green]")
        console.print()
        return True

    console.print("[red]Unknown subcommand. Usage:[/red]")
    console.print("  /images          - List all images")
    console.print("  /images list     - List all images")
    console.print("  /images remove <id> - Remove an image")
    console.print("  /images clear    - Clear all images")
    console.print()
    return True


async def handle_restore_command(cmd_args: str | None) -> bool:
    """Handle /restore [index|path] — recover a file from the snapshot trash.

    With no args: show an interactive numbered list of recent snapshots.
    With an index (e.g. /restore 2) or a path (e.g. /restore src/foo.py):
    restore that snapshot directly.
    """
    mgr = get_recovery_manager()
    if mgr is None:
        console.print()
        console.print("[yellow]No recovery manager active for this session.[/yellow]")
        console.print()
        return True

    snapshots = mgr.list_snapshots(include_past_sessions=True)

    if not snapshots:
        console.print()
        console.print("[yellow]No file snapshots found.[/yellow]")
        console.print(
            "[dim]Snapshots are created automatically before rm, write_file, and edit_file.[/dim]"
        )
        console.print()
        return True

    # ------------------------------------------------------------------
    # If the user gave an argument, try to resolve it without prompting
    # ------------------------------------------------------------------
    if cmd_args:
        arg = cmd_args.strip()
        # Try numeric index
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(snapshots):
                session_id, entry = snapshots[idx]
                _do_restore(mgr, session_id, entry)
                return True
            console.print(f"[red]No snapshot at index {arg}.[/red]")
            console.print()
            return True

        # Try path match (most recent matching snapshot)
        for session_id, entry in snapshots:
            if arg in entry.original_path or entry.original_path.endswith(arg):
                _do_restore(mgr, session_id, entry)
                return True

        console.print(f"[red]No snapshot found matching '{arg}'.[/red]")
        console.print()
        return True

    # ------------------------------------------------------------------
    # Interactive list
    # ------------------------------------------------------------------
    console.print()
    console.print("[bold]File snapshots[/bold] (newest first):")
    console.print()

    now = datetime.now()

    for i, (session_id, entry) in enumerate(snapshots, 1):
        label = REASON_LABELS.get(entry.reason, entry.reason)
        try:
            ts = datetime.fromisoformat(entry.timestamp)
            delta = now - ts
            secs = int(delta.total_seconds())
            if secs < 60:
                age = f"{secs}s ago"
            elif secs < 3600:
                age = f"{secs // 60}m ago"
            elif secs < 86400:
                age = f"{secs // 3600}h ago"
            else:
                age = f"{secs // 86400}d ago"
        except Exception:
            age = entry.timestamp

        console.print(
            f"  [bold cyan][{i}][/bold cyan] {entry.original_path}  "
            f"[dim]— {label}  ({age})[/dim]"
        )

    console.print()
    console.print(
        "[dim]Restore which file? Enter a number, path, or q to cancel:[/dim] ", end=""
    )

    try:
        choice = input().strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return True

    if not choice or choice.lower() == "q":
        console.print()
        return True

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(snapshots):
            session_id, entry = snapshots[idx]
            _do_restore(mgr, session_id, entry)
        else:
            console.print(f"[red]No snapshot at index {choice}.[/red]")
            console.print()
    else:
        for session_id, entry in snapshots:
            if choice in entry.original_path or entry.original_path.endswith(choice):
                _do_restore(mgr, session_id, entry)
                return True
        console.print(f"[red]No snapshot found matching '{choice}'.[/red]")
        console.print()

    return True


def _do_restore(mgr, session_id: str, entry) -> None:
    """Restore a single snapshot entry and print the result."""
    ok = mgr.restore(entry, session_id=session_id)
    console.print()
    if ok:
        console.print(f"[green]Restored:[/green] {entry.original_path}")
    else:
        console.print(f"[red]Failed to restore {entry.original_path}[/red]")
        console.print(
            "[dim]The snapshot file may have been deleted from the trash.[/dim]"
        )
    console.print()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle_files(ctx: CommandContext) -> bool:
        return await handle_files_command()

    async def _handle_images(ctx: CommandContext) -> bool:
        return await handle_images_command(ctx.cmd_args, ctx.image_tracker)

    async def _handle_restore(ctx: CommandContext) -> bool:
        return await handle_restore_command(ctx.cmd_args)

    registry.register("files", _handle_files)
    registry.register("images", _handle_images)
    registry.register("restore", _handle_restore)
