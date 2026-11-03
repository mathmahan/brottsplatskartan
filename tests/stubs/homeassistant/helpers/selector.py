"""Stub selectors: identity validators that record their config.

Enough to prove the flow's schemas build and apply the right defaults. The
real selectors' validation is Home Assistant's own concern.
"""
from enum import StrEnum


class SelectSelectorMode(StrEnum):
    LIST = "list"
    DROPDOWN = "dropdown"


class NumberSelectorMode(StrEnum):
    BOX = "box"
    SLIDER = "slider"


class SelectSelectorConfig(dict):
    pass


class NumberSelectorConfig(dict):
    pass


class _Selector:
    def __init__(self, config):
        self.config = config

    def __call__(self, value):
        return value


class SelectSelector(_Selector):
    pass


class NumberSelector(_Selector):
    pass
