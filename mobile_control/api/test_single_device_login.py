from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from mobile_control.api.helpers.refresh_token import create_refresh_token
from mobile_control.api.helpers.user_auth import end_other_device_sessions
from mobile_control.api.helpers.user_auth import ensure_api_credentials
from mobile_control.api.helpers.user_auth import generate_auth_token
from mobile_control.api.jwt_auth import decode_api_credentials

USER_EMAIL = "single-device@example.com"


def _make_user() -> frappe.model.document.Document:
	if not frappe.db.exists("User", USER_EMAIL):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": USER_EMAIL,
				"first_name": "Single",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", USER_EMAIL)
	ensure_api_credentials(user)
	return frappe.get_doc("User", USER_EMAIL)


def _active_refresh_tokens() -> int:
	return frappe.db.count("Mobile Refresh Token", {"user": USER_EMAIL, "revoked": 0})


class TestSingleDeviceLogin(IntegrationTestCase):
	def setUp(self) -> None:
		self.user = _make_user()
		self.first_device_token = generate_auth_token(self.user)
		create_refresh_token(self.user, device_id="first-device")

	def _set_single_device(self, value: int) -> None:
		frappe.db.set_single_value("Mobile Configuration", "single_device_login", value)

	def _current_secret(self) -> str:
		return frappe.get_doc("User", USER_EMAIL).get_password("api_secret")

	def test_off_leaves_earlier_devices_signed_in(self) -> None:
		self._set_single_device(0)
		end_other_device_sessions(self.user)

		_, secret = decode_api_credentials(self.first_device_token)
		self.assertEqual(secret, self._current_secret())
		self.assertGreater(_active_refresh_tokens(), 0)

	def test_on_voids_earlier_access_and_refresh_tokens(self) -> None:
		self._set_single_device(1)
		end_other_device_sessions(self.user)

		_, old_secret = decode_api_credentials(self.first_device_token)
		self.assertNotEqual(old_secret, self._current_secret())
		self.assertEqual(_active_refresh_tokens(), 0)

	def test_on_the_new_login_token_matches_the_new_secret(self) -> None:
		self._set_single_device(1)
		end_other_device_sessions(self.user)

		user = frappe.get_doc("User", USER_EMAIL)
		ensure_api_credentials(user)
		_, secret = decode_api_credentials(generate_auth_token(user))
		self.assertEqual(secret, self._current_secret())
