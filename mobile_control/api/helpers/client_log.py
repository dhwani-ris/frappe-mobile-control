# mobile_control/api/helpers/client_log.py

"""Mobile client telemetry: parse client info and record device/login activity."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import frappe
from frappe import get_request_header
from frappe.utils import add_days
from frappe.utils import now_datetime

from .constants import REFRESH_TOKEN_TTL_DAYS
from .response_builder import get_request_metadata

CLIENT_INFO_HEADER = "X-Client-Info"

EVENT_LOGIN = "Login"
EVENT_TOKEN_REFRESH = "Token Refresh"
EVENT_LOGOUT = "Logout"

# Frappe Data columns are varchar(140)
MAX_DATA_LENGTH = 140

LOGIN_EVENT_RETENTION_DAYS = 90

# One last_seen write per user per window, so an active app costs a cache hit, not a DB write
LAST_SEEN_THROTTLE_SECONDS = 15 * 60

CLIENT_INFO_FIELDS = (
	"app_name",
	"app_version",
	"build_number",
	"platform",
	"os_version",
	"device_model",
	"device_id",
	"user_agent",
)


HEADER_KEY_MAP = {
	"app": "app_name",
	"ver": "app_version",
	"platform": "platform",
	"os": "os_version",
	"model": "device_model",
	"device": "device_id",
}


def _safe_read(read: Callable[[], Any], default: Any) -> Any:
	"""Request reads raise outside a bound request — telemetry must never break its caller."""
	try:
		return read()
	except Exception:
		return default


def parse_client_info() -> dict[str, Any]:
	"""Parse the X-Client-Info request header into client metadata fields."""
	info = dict.fromkeys(CLIENT_INFO_FIELDS)

	# Legacy channel: pre-header APKs only ever sent a device_id param and the Dart User-Agent.
	legacy_device_id, user_agent = _safe_read(get_request_metadata, (None, None))
	info["device_id"] = legacy_device_id
	info["user_agent"] = user_agent

	header = _safe_read(lambda: get_request_header(CLIENT_INFO_HEADER), None)
	if not header:
		return info

	for part in header.split(";"):
		key, sep, value = part.partition("=")
		if not sep:
			continue
		field = HEADER_KEY_MAP.get(key.strip().lower())
		if field:
			info[field] = value.strip()[:MAX_DATA_LENGTH]

	# "ver" arrives as pubspec-style "2.9.0+72" — split into version and build.
	version = info.get("app_version")
	if version and "+" in version:
		info["app_version"], _sep, info["build_number"] = version.partition("+")

	return info


DEVICE_PROFILE_FIELDS = (
	"app_name",
	"app_version",
	"build_number",
	"platform",
	"os_version",
	"device_model",
	"user_agent",
)


USER_SNAPSHOT_FIELDS = {
	"full_name": "user_full_name",
	"enabled": "user_enabled",
	"user_type": "user_type",
	"mobile_no": "user_mobile_no",
	"phone": "user_phone",
	"last_login": "account_last_login",
	"last_active": "account_last_active",
}


def _user_snapshot(user: str) -> dict[str, Any]:
	"""Copy the user's own details onto the row, as of this event."""
	values = frappe.db.get_value("User", user, list(USER_SNAPSHOT_FIELDS), as_dict=True) or {}
	return {target: values.get(source) for source, target in USER_SNAPSHOT_FIELDS.items()}


def _find_device_log(user: str, device_id: str | None) -> str | None:
	"""Locate this user's row for the device, falling back to the device they were last seen on."""
	if device_id:
		return frappe.db.get_value("Mobile Device Log", {"user": user, "device_id": device_id}, "name")

	# Logout and legacy builds send no device identity — never strand them in a blank row.
	rows = frappe.get_all(
		"Mobile Device Log", filters={"user": user}, fields=["name"], order_by="last_seen desc", limit=1
	)
	return rows[0]["name"] if rows else None


def _upsert_device_log(user: str, info: dict[str, Any], event: str, now: Any) -> str:
	"""Create or refresh the single Mobile Device Log row for this user + device."""
	device_id = info.get("device_id")
	# Keep what an earlier request already told us — a blank field means "not reported", not "cleared".
	values = {field: info.get(field) for field in DEVICE_PROFILE_FIELDS if info.get(field)}
	values.update(_user_snapshot(user))
	values["last_seen"] = now
	values["last_ip"] = _safe_read(lambda: frappe.local.request_ip, None)
	if event == EVENT_LOGIN:
		values["last_login"] = now

	# Login and refresh both mint a refresh token; logout revokes every token for the user.
	if event in (EVENT_LOGIN, EVENT_TOKEN_REFRESH):
		values["session_active"] = 1
		values["token_expires_at"] = add_days(now, REFRESH_TOKEN_TTL_DAYS)
	elif event == EVENT_LOGOUT:
		values["session_active"] = 0
		values["token_expires_at"] = None

	existing = _find_device_log(user, device_id)
	if existing:
		if event == EVENT_LOGIN:
			current = frappe.db.get_value("Mobile Device Log", existing, "login_count") or 0
			values["login_count"] = current + 1
		frappe.db.set_value("Mobile Device Log", existing, values)
		return existing

	doc = frappe.new_doc("Mobile Device Log")
	doc.update(values)
	doc.user = user
	doc.device_id = device_id
	doc.first_seen = now
	doc.login_count = 1 if event == EVENT_LOGIN else 0
	doc.insert(ignore_permissions=True)
	return doc.name


def _insert_login_event(user: str, info: dict[str, Any], event: str, device_log: str, now: Any) -> None:
	"""Append one immutable row to the login history."""
	doc = frappe.new_doc("Mobile Login Event")
	doc.user = user
	doc.event = event
	doc.event_time = now
	doc.device_log = device_log
	doc.ip_address = _safe_read(lambda: frappe.local.request_ip, None)
	for field in ("device_id", "app_version", "build_number", "platform", "os_version", "device_model", "user_agent"):
		doc.set(field, info.get(field))
	doc.insert(ignore_permissions=True)


def record_client_event(event: str, user: str | None = None) -> str | None:
	"""Record a mobile auth event and refresh the user's device row. Never raises."""
	try:
		user = user or frappe.session.user
		info = parse_client_info()
		now = now_datetime()
		device_log = _upsert_device_log(user, info, event, now)
		_insert_login_event(user, info, event, device_log, now)
		return device_log
	except Exception:
		frappe.log_error(title="Mobile Client Log Error", message=frappe.get_traceback())
		return None


def purge_old_login_events() -> None:
	"""Drop login history past the retention window; the device rows are the durable summary."""
	cutoff = add_days(now_datetime(), -LOGIN_EVENT_RETENTION_DAYS)
	frappe.db.delete("Mobile Login Event", {"event_time": ("<", cutoff)})


def last_seen_cache_key(user: str) -> str:
	return f"mobile_last_seen:{user}"


def touch_last_seen(user: str | None = None) -> bool:
	"""Refresh last_seen on an existing device row, at most once per throttle window."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	cache_key = last_seen_cache_key(user)
	if frappe.cache.get_value(cache_key):
		return False

	device_log = _find_device_log(user, parse_client_info().get("device_id"))
	if not device_log:
		return False

	frappe.cache.set_value(cache_key, 1, expires_in_sec=LAST_SEEN_THROTTLE_SECONDS)
	frappe.db.set_value("Mobile Device Log", device_log, "last_seen", now_datetime(), update_modified=False)
	return True


def touch_last_seen_after_request(response: Any = None, request: Any = None) -> None:
	"""after_request hook: frappe commits before this runs, so own the commit here."""
	try:
		if not frappe.local.flags.get("is_mobile_client"):
			return
		if touch_last_seen():
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="Mobile Last Seen Error", message=frappe.get_traceback())
