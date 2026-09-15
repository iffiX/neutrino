"""The language and the palette the panel is drawn in, answered before there
is a session.

The page asks for both before its first render, which is before anybody has
signed in. Writing them is the Settings page's, through
``POST /api/hub/setting/set``.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE, WEB_DEFAULT_THEME
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import PanelDisplay
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/hub/display", tags=["display"])


@router.get("", response_model=PanelDisplay)
def read_display(runtime: PanelRuntime = Depends(get_runtime)) -> PanelDisplay:
    """Read the language and the palette every page is drawn in.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored language, ``en`` where none is stored, and the stored
        palette, ``dark`` where none is stored.
    """
    return PanelDisplay(
        language=str(runtime.settings.get("language", WEB_DEFAULT_LANGUAGE)),
        theme=str(runtime.settings.get("theme", WEB_DEFAULT_THEME)),
    )
