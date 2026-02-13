# mobile_control/api/helpers/refresh_token.py

"""Refresh token management."""

import hashlib
import secrets
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days
from frappe.utils import now_datetime

from .constants import REFRESH_TOKEN_TTL_DAYS


def hash_refresh_token(token: str) -> str:
	"""Hash refresh token for storage."""
	return hashlib.sha256(token.encode()).hexdigest()


def create_refresh_token(user: Any, device_id: str | None = None, user_agent: str | None = None) -> str:
	"""Create a new refresh token for user."""
	raw_token = secrets.token_urlsafe(32)
	token_hash = hash_refresh_token(raw_token)
	refresh_doc = frappe.new_doc("Mobile Refresh Token")
	refresh_doc.user = user.name
	refresh_doc.token_hash = token_hash
	refresh_doc.expires_at = add_days(now_datetime(), REFRESH_TOKEN_TTL_DAYS)
	refresh_doc.revoked = 0
	refresh_doc.last_used = now_datetime()
	if device_id:
		refresh_doc.device_id = device_id
	if user_agent:
		refresh_doc.user_agent = user_agent
	refresh_doc.insert(ignore_permissions=True)
	return raw_token


def get_valid_refresh_token_doc(refresh_token: str) -> dict[str, Any]:
	"""Get and validate refresh token document."""
	if not refresh_token:
		frappe.throw(_("Refresh token is required"), frappe.ValidationError)

	token_hash = hash_refresh_token(refresh_token)
	token_docs = frappe.get_all(
		"Mobile Refresh Token",
		filters={"token_hash": token_hash, "revoked": 0},
		fields=["name", "user", "expires_at"],
		limit=1,
	)
	if not token_docs:
		raise frappe.AuthenticationError(_("Invalid refresh token"))

	token_doc = token_docs[0]
	if token_doc.get("expires_at") and now_datetime() > token_doc["expires_at"]:
		frappe.db.set_value(
			"Mobile Refresh Token",
			token_doc["name"],
			{"revoked": 1, "last_used": now_datetime()},
		)
		raise frappe.AuthenticationError(_("Refresh token expired"))

	return token_doc


def rotate_refresh_token(token_doc: dict[str, Any], user: Any) -> str:
	"""Revoke old refresh token and create a new one."""
	frappe.db.set_value(
		"Mobile Refresh Token",
		token_doc["name"],
		{"revoked": 1, "last_used": now_datetime()},
	)
	return create_refresh_token(user)


def revoke_refresh_tokens_for_user(user: Any) -> None:
	"""Revoke all active refresh tokens for a user."""
	token_names = frappe.get_all(
		"Mobile Refresh Token",
		filters={"user": user.name, "revoked": 0},
		pluck="name",
	)
	for token_name in token_names:
		frappe.db.set_value(
			"Mobile Refresh Token",
			token_name,
			{"revoked": 1, "last_used": now_datetime()},
		)
