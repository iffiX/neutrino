"""The channel's frames and sections, pinned as JSON schemas.

``channel_schema.json`` is the golden: the protocol number and one schema per
``Channel*`` model in ``web/models.py``. What is pinned is that the number is
the golden's, that the model set is closed, and that each model's schema is
its golden's. A change here fails until ``PROTOCOL`` moves or the change is
shown to be additive; nothing regenerates the file.
"""

import inspect
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from neutrino_hub.modules.channel.constants import PROTOCOL
from neutrino_hub.web import models

GOLDEN_PATH = Path(__file__).with_name("channel_schema.json")
CHANNEL_PREFIX = "Channel"


def channel_models() -> dict:
    """Every channel model, by name."""
    return {
        name: model
        for name, model in inspect.getmembers(models, inspect.isclass)
        if name.startswith(CHANNEL_PREFIX)
        and issubclass(model, BaseModel)
        and model.__module__ == models.__name__
    }


def golden() -> dict:
    """The pinned schemas."""
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_the_protocol_number_is_the_goldens():
    assert PROTOCOL == golden()["protocol"]


def test_the_model_set_is_closed():
    assert set(channel_models()) == set(golden()["models"])


@pytest.mark.parametrize("name", sorted(channel_models()))
def test_each_models_schema_is_its_golden(name):
    assert channel_models()[name].model_json_schema() == golden()["models"][name]
