"""What the job registry keeps and what it lets go.

Every install, reboot and password set holds up to two thousand lines for as
long as the panel runs. A gateway is up for months, so what it keeps has to be
bounded — but not to nothing: a drawer reopened after an install still shows
that install's log.
"""

import asyncio

from neutrino_hub.web.task_stream import FINISHED_TASK_LIMIT, TaskStreamRegistry


async def _one_line(text: str):
    yield text


async def _never_finishes():
    yield "working"
    await asyncio.sleep(30)


async def _settle() -> None:
    """Let the drain task run to the end of whatever it was given."""
    for _ in range(3):
        await asyncio.sleep(0)


def test_the_finished_jobs_are_bounded():
    async def run():
        registry = TaskStreamRegistry()
        for index in range(FINISHED_TASK_LIMIT + 5):
            registry.start(label=f"install {index}", source=_one_line("done"))
            await _settle()
        return registry

    registry = asyncio.run(run())

    assert registry.running_all() == []
    assert len(registry.streams()) <= FINISHED_TASK_LIMIT + 1


def test_the_most_recent_log_survives():
    """It is the one a drawer reopens on."""

    async def run():
        registry = TaskStreamRegistry()
        kept = None
        for index in range(FINISHED_TASK_LIMIT + 5):
            kept = registry.start(label=f"install {index}", source=_one_line("done"))
            await _settle()
        return registry, kept

    registry, kept = asyncio.run(run())

    assert registry.get(kept.id) is not None


def test_a_running_job_is_never_evicted():
    async def run():
        registry = TaskStreamRegistry()
        running = registry.start(label="install slow", source=_never_finishes())
        await _settle()
        for index in range(FINISHED_TASK_LIMIT + 5):
            registry.start(label=f"install {index}", source=_one_line("done"))
            await _settle()
        # Read before the loop closes: shutting it down cancels the job, which
        # is what finishing one looks like from here.
        return registry.get(running.id), [s.id for s in registry.running_all()]

    held, still_running = asyncio.run(run())

    assert held is not None
    assert still_running == [held.id]
