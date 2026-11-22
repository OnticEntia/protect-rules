"""The dashboard card: served by the integration and loaded into Home Assistant.

The card lives in frontend/ next to this file, so one install brings the
backend and the card that goes with it. It is served at an address that
carries the integration's version:

    /protect_rules/frontend/<version>/protect-rules-card.js

and Home Assistant's frontend is told to load it as an extra module, so no
dashboard resource has to be added by hand. Nothing is written to Home
Assistant's storage: unloading (or removing) the integration takes the card
out again, and a new version is a new address, which no browser has a stale
copy of. The file is also sent with "no-cache", so a browser checks each time
that its copy is still the one on disk.
"""

from __future__ import annotations

from pathlib import Path
import re

from aiohttp import web

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

DOMAIN = "protect_rules"
URL_BASE = "/protect_rules/frontend"
FRONTEND_DIR = Path(__file__).parent / "frontend"
CARDS = ("protect-rules-card.js",)
_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\.js")


class CardsView(HomeAssistantView):
    """The files in frontend/. Public, as Home Assistant's own frontend files
    are: they hold no data, and a page loads them before it has logged in."""

    url = URL_BASE + "/{version}/{name}"
    name = "protect_rules:frontend"
    requires_auth = False

    async def get(self, request: web.Request, version: str, name: str) -> web.StreamResponse:
        if not _NAME.fullmatch(name):
            return web.Response(status=404)
        path = FRONTEND_DIR / name
        if not await request.app["hass"].async_add_executor_job(path.is_file):
            return web.Response(status=404)
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


async def async_card_urls(hass: HomeAssistant) -> list[str]:
    """Where this version's card is served."""
    integration = await async_get_integration(hass, DOMAIN)
    return [f"{URL_BASE}/{integration.version}/{name}" for name in CARDS]


def load_cards(hass: HomeAssistant, urls: list[str]) -> None:
    """Have the frontend load the card (the same address twice counts once)."""
    for url in urls:
        add_extra_js_url(hass, url)


def unload_cards(hass: HomeAssistant, urls: list[str]) -> None:
    for url in urls:
        try:
            remove_extra_js_url(hass, url)
        except KeyError:  # already gone
            pass
