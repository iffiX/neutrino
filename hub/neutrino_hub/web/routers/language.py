"""The language the panel is drawn in, answered before there is a session.

The page asks for it before its first render, which is before anybody has
signed in: a login card in the wrong language is the one screen a session
cannot fix. Writing it is the Settings tab's, through ``/api/settings``.
"""

from fastapi import APIRouter, Depends

from neutrino_hub.web.constants import WEB_DEFAULT_LANGUAGE
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import PanelLanguage
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(prefix="/api/language", tags=["language"])


@router.get("", response_model=PanelLanguage)
def read_language(runtime: PanelRuntime = Depends(get_runtime)) -> PanelLanguage:
    """Read the language every page is drawn in.

    Args:
        runtime: The shared runtime.

    Returns:
        The stored language, ``en`` where none is stored.
    """
    return PanelLanguage(
        language=str(runtime.settings.get("language", WEB_DEFAULT_LANGUAGE))
    )
