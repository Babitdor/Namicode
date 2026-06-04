# Trello Board — Auto-Process Loaded Tasks

## Problem

The `/trello` watch loop only picked up tasks that were explicitly moved to `"processing"` status by clicking the **"Start"** button in the web UI. Newly added tasks sat in `"loaded"` status forever and were never automatically processed.

## Changes

### 1. `novacode_cli/commands/trello_server.py` — New method `pop_next_loaded_task()`

Added a method to `TrelloServer` that finds the first task in `"loaded"` status, marks it as `"processing"`, and returns it:

```python
def pop_next_loaded_task(self) -> dict | None:
    """Pop the next 'loaded' task and mark it as 'processing'.

    Returns:
        The task dict if one was available, or None.
    """
    with self._lock:
        for task in self._tasks:
            if task.get("status") == "loaded":
                task["status"] = "processing"
                return task.copy()
    return None
```

### 2. `novacode_cli/tui/app.py` — Updated `_trello_watch_loop()`

The watch loop now falls back to `pop_next_loaded_task()` when no explicit processing notification arrives:

```python
async def _trello_watch_loop(self, server: Any) -> None:
    """Background loop: poll for processing tasks and execute them."""
    try:
        while server.is_running:
            # First check for tasks explicitly moved to "processing" (web UI click)
            task = await server.get_next_processing_task()
            if not task:
                # Auto-pick the first "loaded" task
                task = server.pop_next_loaded_task()
            if task:
                ...
```

## Behavior

| Action | Before | After |
|--------|--------|-------|
| Add task via web UI | Sits in "loaded" forever | Auto-picked and processed |
| Click "Start" in web UI | Processed | Processed (still works) |
| Multiple tasks added | None processed | Processed one at a time in FIFO order |
