import frappe
from frappe.utils import now_datetime


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
