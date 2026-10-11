"""Repair flows for APC UPS NMC."""

from __future__ import annotations

from ipaddress import ip_address
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from . import SYSLOG_LISTENER_CONFLICT_ISSUE, SYSLOG_LISTENER_FAILED_ISSUE
from .const import (
    CONF_SYSLOG_BIND_ADDRESS,
    CONF_SYSLOG_ENABLED,
    CONF_SYSLOG_PORT,
)
from .coordinator import SYSLOG_PARSE_FAILURE_ISSUE
from .syslog import (
    DEFAULT_SYSLOG_BIND_ADDRESS,
    DEFAULT_SYSLOG_ENABLED,
    DEFAULT_SYSLOG_PORT,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

type IssueData = dict[str, str | int | float | None]


class SyslogListenerRepairFlow(RepairsFlow):
    """Repair syslog listener bind settings for a config entry."""

    def __init__(self, entry: ConfigEntry, placeholders: dict[str, str]) -> None:
        """Initialize the syslog listener repair flow."""
        self.entry = entry
        self.placeholders = placeholders

    async def async_step_init(
        self,
        _user_input: dict[str, Any] | None = None,
    ) -> RepairsFlowResult:
        """Handle the initial step."""
        return await self.async_step_syslog_options()

    async def async_step_syslog_options(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> RepairsFlowResult:
        """Handle syslog listener option changes."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                bind_address = _normalize_bind_address(
                    user_input[CONF_SYSLOG_BIND_ADDRESS]
                )
            except ValueError:
                errors[CONF_SYSLOG_BIND_ADDRESS] = "invalid_syslog_bind_address"
            else:
                options = dict(self.entry.options)
                options[CONF_SYSLOG_ENABLED] = bool(user_input[CONF_SYSLOG_ENABLED])
                options[CONF_SYSLOG_BIND_ADDRESS] = bind_address
                options[CONF_SYSLOG_PORT] = int(user_input[CONF_SYSLOG_PORT])
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    options=options,
                )
                await self.hass.config_entries.async_reload(self.entry.entry_id)
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="syslog_options",
            data_schema=_syslog_options_schema(self.entry, user_input),
            errors=errors,
            description_placeholders=self.placeholders,
        )


class SyslogParseFailureRepairFlow(RepairsFlow):
    """Repair syslog parse failures for a config entry."""

    def __init__(self, entry: ConfigEntry, placeholders: dict[str, str]) -> None:
        """Initialize the syslog parse-failure repair flow."""
        self.entry = entry
        self.placeholders = placeholders

    async def async_step_init(
        self,
        _user_input: dict[str, Any] | None = None,
    ) -> RepairsFlowResult:
        """Handle the initial step."""
        return await self.async_step_confirm_disable()

    async def async_step_confirm_disable(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> RepairsFlowResult:
        """Disable syslog for the affected entry when confirmed."""
        if user_input is not None:
            options = dict(self.entry.options)
            options[CONF_SYSLOG_ENABLED] = False
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            await self.hass.config_entries.async_reload(self.entry.entry_id)
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm_disable",
            data_schema=probatio.Schema({}),
            description_placeholders=self.placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: IssueData | None,
) -> RepairsFlow:
    """Create a repair flow for a syslog issue."""
    if data is None:
        raise ValueError(f"repair issue {issue_id} is missing data")

    entry = _entry_from_issue_data(hass, issue_id, data)
    placeholders = _placeholders(data)
    if issue_id.startswith(
        (f"{SYSLOG_LISTENER_CONFLICT_ISSUE}_", f"{SYSLOG_LISTENER_FAILED_ISSUE}_")
    ):
        return SyslogListenerRepairFlow(entry, placeholders)

    if issue_id.startswith(f"{SYSLOG_PARSE_FAILURE_ISSUE}_"):
        return SyslogParseFailureRepairFlow(entry, placeholders)

    raise ValueError(f"unknown repair issue {issue_id}")


def _entry_from_issue_data(
    hass: HomeAssistant,
    issue_id: str,
    data: IssueData,
) -> ConfigEntry:
    """Return the config entry referenced by repair issue data."""
    entry_id = data.get("entry_id")
    if not isinstance(entry_id, str):
        raise TypeError(f"repair issue {issue_id} is missing entry_id")

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError(f"repair issue {issue_id} references unknown entry")

    return entry


def _placeholders(data: IssueData) -> dict[str, str]:
    """Return string placeholders for repair flow descriptions."""
    return {
        key: str(value)
        for key, value in data.items()
        if key != "entry_id" and value is not None
    }


def _syslog_options_schema(
    entry: ConfigEntry,
    user_input: dict[str, Any] | None,
) -> probatio.Schema:
    """Return the syslog listener repair option schema."""
    defaults = dict(entry.data) | dict(entry.options)
    if user_input is not None:
        defaults |= user_input

    return probatio.Schema(
        {
            probatio.Required(
                CONF_SYSLOG_ENABLED,
                default=defaults.get(CONF_SYSLOG_ENABLED, DEFAULT_SYSLOG_ENABLED),
            ): bool,
            probatio.Required(
                CONF_SYSLOG_BIND_ADDRESS,
                default=defaults.get(
                    CONF_SYSLOG_BIND_ADDRESS,
                    DEFAULT_SYSLOG_BIND_ADDRESS,
                ),
            ): str,
            probatio.Required(
                CONF_SYSLOG_PORT,
                default=defaults.get(CONF_SYSLOG_PORT, DEFAULT_SYSLOG_PORT),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=65535,
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _normalize_bind_address(value: Any) -> str:
    """Return a normalized IP literal for syslog listener binding."""
    return str(ip_address(str(value).strip()))
