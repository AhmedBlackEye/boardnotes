"""Single source of truth for data shapes shared between modules and with the web app.

Do not change these without updating docs/decisions.md and regenerating web types (`make contracts`).
"""

from . import ai, api, enums

__all__ = ["ai", "api", "enums"]
