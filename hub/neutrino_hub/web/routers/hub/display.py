"""The language and the palette the panel is drawn in, answered before there
is a session, and an update of the hub itself.

The page asks for both before its first render, which is before anybody has
signed in. Writing them is the Settings page's, through
``POST /api/hub/setting/set``. An update restarts the panel, which ends every
session, so the page follows the update's steps here until it ends.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_DISPLAY_WINDOW_S,
    HUB_UPDATE_STAGES_SETTLED,
    HUB_UPDATE_TASK_LABEL,
)
from neutrino_hub.modules.hub_update.installer import HubUpdateInstaller
from neutrino_hub.modules.hub_update.release import HubReleaseChecker
from neutrino_hub.modules.hub_update.state import (
    HubUpdateRecord,
    HubUpdateStateFile,
    stamp_age_s,
)
from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE, WEB_DEFAULT_THEME
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import PanelDisplay, PanelDisplayUpdate
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/hub/display", tags=["display"])


@router.get("", response_model=PanelDisplay)
def read_display(runtime: PanelRuntime = Depends(get_runtime)) -> PanelDisplay:
    """Read the language and the palette every page is drawn in.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored language, ``en`` where none is stored, the stored
        palette, ``dark`` where none is stored, and the hub's update while
        it runs or for 30 minutes after it ended, with a run that died
        marked as such.
    """
    running = runtime.tasks.running(HUB_UPDATE_TASK_LABEL)
    record = _update_installer().settled_record(is_task_running=running is not None)
    return PanelDisplay(
        language=str(runtime.settings.get("language", WEB_DEFAULT_LANGUAGE)),
        theme=str(runtime.settings.get("theme", WEB_DEFAULT_THEME)),
        update=_shown(record),
    )


def _shown(record: HubUpdateRecord | None) -> PanelDisplayUpdate | None:
    """The update as a page with no session reads it, when it is still news.

    Args:
        record: The update's record, settled.

    Returns:
        Its stage, versions, steps and end; None with no record, or one that
        ended more than 30 minutes ago.
    """
    if record is None:
        return None
    if record.stage in HUB_UPDATE_STAGES_SETTLED:
        age = stamp_age_s(record.finished_at)
        if age is None or age > HUB_UPDATE_DISPLAY_WINDOW_S:
            return None
    return PanelDisplayUpdate(
        stage=record.stage,
        from_version=record.from_version,
        to_version=record.to_version,
        steps=record.steps,
        finished_at=record.finished_at,
    )


def _update_installer() -> HubUpdateInstaller:
    """The installer whose record this route reads; a test replaces this.

    Returns:
        An installer over the real state file.
    """
    return HubUpdateInstaller(checker=HubReleaseChecker(), state=HubUpdateStateFile())
