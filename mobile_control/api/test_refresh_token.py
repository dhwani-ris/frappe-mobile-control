from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days
from frappe.utils import now_datetime
from mobile_control.api import api_auth
from mobile_control.api.helpers.refresh_token import create_refresh_token
from mobile_control.api.helpers.refresh_token import hash_refresh_token
from mobile_control.api.helpers.user_auth import ensure_api_credentials

MOBILE_USER_EMAIL = "refresh-mobile@example.com"
NON_MOBILE_USER_EMAIL = "refresh-plain@example.com"


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _make_user(email: str, mobile: bool) -> frappe.model.document.Document:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Refresh",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	if mobile:
		_ensure_role("Mobile User")
		user.add_roles("Mobile User")
	ensure_api_credentials(user)
	return frappe.get_doc("User", email)


class TestRefreshTokenEndpoint(IntegrationTestCase):
	"""Regression tests for api_auth.refresh_token (PR #37).

	Covers the two behaviours the fix introduced:
	  1. Tokens are written to the TOP LEVEL of frappe.local.response (mirroring
	     `login`), not returned as a dict that Frappe would nest under `message`.
	  2. Failures raise typed exceptions so the correct HTTP status propagates
	     (AuthenticationError -> 401, PermissionError -> 403, ValidationError -> 417).
	"""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.mobile_user = _make_user(MOBILE_USER_EMAIL, mobile=True)
		cls.plain_user = _make_user(NON_MOBILE_USER_EMAIL, mobile=False)

	def _reset_response(self) -> None:
		for key in ("access_token", "refresh_token", "message"):
			frappe.local.response.pop(key, None)

	# --- success: tokens land top-level (the core regression guard) ---------

	def test_refresh_returns_tokens_at_top_level(self) -> None:
		raw = create_refresh_token(self.mobile_user, device_id="dev-1", user_agent="ua-1")
		self._reset_response()

		result = api_auth.refresh_token(raw)

		# The endpoint writes to frappe.local.response and returns None, so Frappe
		# does not wrap the payload under `message`.
		self.assertIsNone(result)
		self.assertIn("access_token", frappe.local.response)
		self.assertTrue(frappe.local.response["access_token"])
		self.assertIn("refresh_token", frappe.local.response)
		# Rotation: the returned refresh token is a fresh one, not the used token.
		self.assertNotEqual(frappe.local.response["refresh_token"], raw)
		# `message` is a plain label sitting alongside the tokens, NOT a wrapper
		# dict containing them (the old bug nested everything under `message`).
		self.assertEqual(frappe.local.response.get("message"), "Token refreshed")

	def test_refresh_rotates_old_token(self) -> None:
		raw = create_refresh_token(self.mobile_user, device_id="dev-2", user_agent="ua-2")
		self._reset_response()

		api_auth.refresh_token(raw)

		# Re-using the now-rotated token must fail as an auth error.
		self._reset_response()
		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.refresh_token(raw)
		self.assertEqual(cm.exception.http_status_code, 401)

	# --- error mapping: correct HTTP status codes ---------------------------

	def test_invalid_refresh_token_returns_401(self) -> None:
		self._reset_response()
		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.refresh_token("this-token-does-not-exist")
		self.assertEqual(cm.exception.http_status_code, 401)

	def test_expired_refresh_token_returns_401(self) -> None:
		raw = create_refresh_token(self.mobile_user, device_id="dev-3", user_agent="ua-3")
		# Match the exact row we just created by its stored hash (robust against
		# same-second `creation` ties with tokens from earlier tests).
		token_name = frappe.get_value("Mobile Refresh Token", {"token_hash": hash_refresh_token(raw)}, "name")
		frappe.db.set_value("Mobile Refresh Token", token_name, "expires_at", add_days(now_datetime(), -1))
		self._reset_response()

		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.refresh_token(raw)
		self.assertEqual(cm.exception.http_status_code, 401)

	def test_user_without_mobile_role_returns_403(self) -> None:
		raw = create_refresh_token(self.plain_user, device_id="dev-4", user_agent="ua-4")
		self._reset_response()

		with self.assertRaises(frappe.PermissionError) as cm:
			api_auth.refresh_token(raw)
		self.assertEqual(cm.exception.http_status_code, 403)

	def test_missing_refresh_token_returns_417(self) -> None:
		self._reset_response()
		with self.assertRaises(frappe.ValidationError) as cm:
			api_auth.refresh_token("")
		self.assertEqual(cm.exception.http_status_code, 417)
