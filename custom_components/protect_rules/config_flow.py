"""One-click setup: uses the existing UniFi Protect integration's connection."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import DOMAIN, _protect_api, async_zones_stream


class ProtectRulesFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if await async_zones_stream(self.hass) is None:
            return self.async_abort(reason="zones_not_installed")
        if _protect_api(self.hass) is None:
            return self.async_abort(reason="protect_not_loaded")
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="Protect Rules", data={})
