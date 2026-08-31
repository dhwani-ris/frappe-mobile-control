import frappe
from frappe.utils import add_to_date
from frappe.utils import now_datetime
from mobile_control.api.helpers.client_log import purge_old_login_events


def cleanup_mobile_refresh_tokens() -> None:
	"""Delete revoked or expired mobile refresh tokens."""
	now = now_datetime()
	expired_count = frappe.db.count("Mobile Refresh Token", {"expires_at": ("<", now)})
	revoked_count = frappe.db.count("Mobile Refresh Token", {"revoked": 1})

	if expired_count:
		frappe.db.delete("Mobile Refresh Token", {"expires_at": ("<", now)})

	if revoked_count:
		frappe.db.delete("Mobile Refresh Token", {"revoked": 1})

	if expired_count or revoked_count:
		frappe.logger("mobile_control").info(
			"Cleaned Mobile Refresh Tokens (expired=%s, revoked=%s)",
			expired_count,
			revoked_count,
		)


def purge_mobile_error_logs() -> None:
	"""Delete Mobile Error Log rows older than the configured retention.

	Retention days come from the Mobile Configuration single (default 30).
	A value of 0 disables purging. Mirrors Frappe Error Log's clear_old_logs.
	"""
	days = frappe.db.get_single_value("Mobile Configuration", "mobile_error_log_retention_days")
	try:
		days = int(days)
	except (TypeError, ValueError):
		days = 30
	if days <= 0:
		return

	cutoff = add_to_date(now_datetime(), days=-days)
	count = frappe.db.count("Mobile Error Log", {"last_seen": ("<", cutoff)})
	if count:
		frappe.db.delete("Mobile Error Log", {"last_seen": ("<", cutoff)})
		frappe.logger("mobile_control").info("Purged %s Mobile Error Log rows", count)


def cleanup_mobile_login_events() -> None:
	"""Trim mobile login history past its retention window."""
	purge_old_login_events()
