"""The palette the panel is drawn in, answered before there is a session.

The page asks for it before its first render, which is before anybody has
signed in: a login card that flashes the other palette is the one screen a
session cannot fix. Writing it is the Settings tab's, through
``/api/settings``.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.web.constants import WEB_DEFAULT_THEME
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import PanelTheme
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/theme", tags=["theme"])


@router.get("", response_model=PanelTheme)
def read_theme(runtime: PanelRuntime = Depends(get_runtime)) -> PanelTheme:
    """Read the palette every page is drawn in.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored theme, ``dark`` where none is stored.
    """
    return PanelTheme(theme=str(runtime.settings.get("theme", WEB_DEFAULT_THEME)))
