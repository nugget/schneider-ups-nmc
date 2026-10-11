"""Constants for APC UPS NMC."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "schneider_ups_nmc"
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
]

CONF_AUTH_KEY = "auth_key"
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_COMMUNITY = "community"
CONF_PRIVACY_KEY = "privacy_key"
CONF_PRIVACY_PROTOCOL = "privacy_protocol"
CONF_SNMP_VERSION = "snmp_version"
CONF_SYSLOG_BIND_ADDRESS = "syslog_bind_address"
CONF_SYSLOG_ENABLED = "syslog_enabled"
CONF_SYSLOG_LOG_RAW_MESSAGES = "syslog_log_raw_messages"
CONF_SYSLOG_PORT = "syslog_port"
CONF_USERNAME = "username"
CONF_WEB_URL = "web_url"

DEFAULT_PORT = 161
DEFAULT_RETRIES = 1
DEFAULT_SCAN_INTERVAL = 60
DEFAULT_TIMEOUT = 2.0
SYSLOG_MANAGER = "syslog_manager"
TROUBLESHOOTING_URL = "https://github.com/nugget/schneider-ups-nmc#troubleshooting"
