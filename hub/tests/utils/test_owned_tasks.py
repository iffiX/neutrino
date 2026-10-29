"""Background tasks kept referenced until they end.

What these pin: a task waiting on a future only it references survives a
garbage collection and is let go once it ends, and no hub source starts a
task and drops it.
"""

import ast
import asyncio
import gc
from pathlib import Path

from neutrino_hub.utils import owned_tasks
from neutrino_hub.utils.owned_tasks import start_owned_task

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "neutrino_hub"
# The calls that start a task.
TASK_STARTERS = ("create_task", "ensure_future")


async def _wait_forever():
    await asyncio.get_running_loop().create_future()


def _tasks_running(name: str) -> list:
    return [task for task in asyncio.all_tasks() if task.get_coro().__name__ == name]


def test_a_task_waiting_on_its_own_future_survives_a_collection():
    async def scenario():
        start_owned_task(_wait_forever())
        await asyncio.sleep(0)
        gc.collect()
        kept = _tasks_running("_wait_forever")
        for task in kept:
            task.cancel()
        await asyncio.gather(*kept, return_exceptions=True)
        return len(kept), len(owned_tasks._RUNNING)

    assert asyncio.run(scenario()) == (1, 0)


def test_no_hub_source_starts_a_task_and_drops_it():
    dropped = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            called = node.value.func
            name = getattr(called, "attr", getattr(called, "id", ""))
            if name in TASK_STARTERS:
                dropped.append(f"{path.relative_to(PACKAGE_ROOT)}:{node.lineno}")

    assert dropped == []
