"""Background tasks kept referenced until they end.

The event loop keeps only a weak reference to a task. A task nothing else
references can be collected while it waits, and asyncio then logs "Task was
destroyed but it is pending!". Every task the hub starts and does not await
starts through :func:`start_owned_task`.
"""

import asyncio

# Every task started here that has not ended.
_RUNNING: set = set()


def start_owned_task(coroutine) -> asyncio.Task:
    """Start a task on the running loop and keep it until it ends.

    Args:
        coroutine: The coroutine the task runs.

    Returns:
        The task.

    Raises:
        RuntimeError: When no event loop runs in this thread.
    """
    task = asyncio.get_running_loop().create_task(coroutine)
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return task
