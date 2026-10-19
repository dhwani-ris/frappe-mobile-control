from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from mobile_control.api import api_auth
from mobile_control.api.helpers.user_auth import ensure_api_credentials

MOBILE_OTP_USER_EMAIL = "otp-mobile@example.com"
MOBILE_OTP_USER_PHONE = "9876500001"
NON_MOBILE_OTP_USER_EMAIL = "otp-plain@example.com"
NON_MOBILE_OTP_USER_PHONE = "9876500002"

SEND_OTP_PATH = "mobile_control.api.mobile_otp.send_token_via_sms"


def _ensure_role(role: str) -> None:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)


def _make_user(email: str, mobile_no: str, mobile: bool) -> frappe.model.document.Document:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		user.mobile_no = mobile_no
		user.enabled = 1
		user.save(ignore_permissions=True)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Otp",
				"send_welcome_email": 0,
				"enabled": 1,
				"mobile_no": mobile_no,
			}
		).insert(ignore_permissions=True)
	if mobile:
		_ensure_role("Mobile User")
		user.add_roles("Mobile User")
	ensure_api_credentials(user)
	return frappe.get_doc("User", email)


class TestMobileOtpLogin(IntegrationTestCase):
	"""Unit tests for issue #138 (OTP-based login): api_auth.send_mobile_otp
	and api_auth.verify_mobile_otp.

	SMS dispatch is mocked throughout (`send_token_via_sms` patched) so these
	tests never attempt a real SMS send; the OTP value itself is read back
	from cache (the exact key `mobile_otp.cache_mobile_otp_data` writes),
	mirroring how a real device would receive it over SMS.
	"""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.mobile_user = _make_user(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE, mobile=True)
		cls.plain_user = _make_user(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE, mobile=False)

		cls._prior_mobile_login_setting = frappe.db.get_single_value(
			"System Settings", "allow_login_using_mobile_number"
		)
		settings = frappe.get_single("System Settings")
		settings.allow_login_using_mobile_number = 1
		settings.save(ignore_permissions=True)

		cls._prior_sms_gateway_url = frappe.db.get_single_value("SMS Settings", "sms_gateway_url")
		sms_settings = frappe.get_single("SMS Settings")
		sms_settings.sms_gateway_url = "https://sms.example.test/send"
		sms_settings.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls) -> None:
		settings = frappe.get_single("System Settings")
		settings.allow_login_using_mobile_number = cls._prior_mobile_login_setting
		settings.save(ignore_permissions=True)

		sms_settings = frappe.get_single("SMS Settings")
		sms_settings.sms_gateway_url = cls._prior_sms_gateway_url
		sms_settings.save(ignore_permissions=True)
		super().tearDownClass()

	def setUp(self) -> None:
		super().setUp()
		self._reset_response()

	def tearDown(self) -> None:
		self._reset_response()
		super().tearDown()

	def _reset_response(self) -> None:
		for key in (
			"access_token",
			"refresh_token",
			"message",
			"tmp_id",
			"mobile_no",
			"prompt",
			"user",
		):
			frappe.local.response.pop(key, None)

	def _send_otp(self, mobile_no: str) -> tuple[str, str]:
		"""Sends an OTP (SMS mocked) and returns (tmp_id, otp) read back from
		cache, exactly as a device would receive tmp_id in the response and
		the OTP over SMS."""
		with patch(SEND_OTP_PATH, return_value=True):
			api_auth.send_mobile_otp(mobile_no)
		tmp_id = frappe.local.response["tmp_id"]
		self.assertTrue(tmp_id)
		token = frappe.cache.get(tmp_id + "_token")
		if isinstance(token, bytes):
			token = token.decode("utf-8")
		self.assertIsNotNone(token, "send_mobile_otp must cache the OTP for verify_mobile_otp to check")
		return tmp_id, str(token)

	# --- send_mobile_otp ------------------------------------------------

	def test_send_otp_returns_tmp_id_and_masks_mobile_no(self) -> None:
		tmp_id, _otp = self._send_otp(MOBILE_OTP_USER_PHONE)

		self.assertTrue(tmp_id)
		self.assertEqual(frappe.local.response["mobile_no"], "987XXXXXXX")
		# The TOTP secret must never leave the server in the response.
		self.assertNotIn("otp_secret", frappe.local.response)

	def test_send_otp_unknown_mobile_number_is_rejected(self) -> None:
		with self.assertRaises(frappe.AuthenticationError):
			api_auth.send_mobile_otp("0000000000")
		self.assertNotIn("tmp_id", frappe.local.response)

	def test_send_otp_dispatch_failure_raises(self) -> None:
		with patch(SEND_OTP_PATH, return_value=False):
			with self.assertRaises(frappe.AuthenticationError):
				api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)

	def test_send_otp_rejected_when_feature_disabled(self) -> None:
		settings = frappe.get_single("System Settings")
		settings.allow_login_using_mobile_number = 0
		settings.save(ignore_permissions=True)
		try:
			with self.assertRaises(frappe.AuthenticationError):
				api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)
		finally:
			settings.allow_login_using_mobile_number = 1
			settings.save(ignore_permissions=True)

	# --- verify_mobile_otp ------------------------------------------------

	def test_verify_otp_completes_login_with_tokens_at_top_level(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_PHONE)
		self._reset_response()

		result = api_auth.verify_mobile_otp(tmp_id, otp)

		# Mirrors test_refresh_token.py's regression guard: the endpoint writes
		# straight to frappe.local.response, so Frappe does not wrap the
		# payload under `message`.
		self.assertIsNone(result)
		self.assertIn("access_token", frappe.local.response)
		self.assertTrue(frappe.local.response["access_token"])
		self.assertIn("refresh_token", frappe.local.response)
		self.assertTrue(frappe.local.response["refresh_token"])
		self.assertEqual(frappe.local.response.get("user"), MOBILE_OTP_USER_EMAIL)

	def test_otp_is_single_use(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_PHONE)
		self._reset_response()
		api_auth.verify_mobile_otp(tmp_id, otp)

		self._reset_response()
		with self.assertRaises(frappe.AuthenticationError):
			api_auth.verify_mobile_otp(tmp_id, otp)

	def test_invalid_otp_is_rejected(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_PHONE)
		self._reset_response()
		wrong_otp = "".join("1" if digit != "1" else "2" for digit in otp)

		with self.assertRaises(frappe.AuthenticationError):
			api_auth.verify_mobile_otp(tmp_id, wrong_otp)

	def test_verify_otp_user_without_mobile_role_is_rejected(self) -> None:
		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()

		with self.assertRaises(frappe.PermissionError):
			api_auth.verify_mobile_otp(tmp_id, otp)

	def test_verify_otp_missing_params_returns_417(self) -> None:
		with self.assertRaises(frappe.ValidationError) as cm:
			api_auth.verify_mobile_otp("", "")
		self.assertEqual(cm.exception.http_status_code, 417)

	def test_verify_otp_unknown_tmp_id_is_rejected(self) -> None:
		with self.assertRaises(frappe.AuthenticationError):
			api_auth.verify_mobile_otp("does-not-exist", "123456")
