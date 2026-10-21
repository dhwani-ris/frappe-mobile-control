from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import frappe
import pyotp
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from mobile_control.api import api_auth
from mobile_control.api.helpers.user_auth import ensure_api_credentials

MOBILE_OTP_USER_EMAIL = "otp-mobile@example.com"
NON_MOBILE_OTP_USER_EMAIL = "otp-plain@example.com"

# Ofcom reserves 07700 900000-900999 for drama and documentation and never
# allocates it to a subscriber, so a call that somehow slips past the SMS
# patches below still cannot text a real person.
MOBILE_OTP_USER_PHONE = "+447700900001"
NON_MOBILE_OTP_USER_PHONE = "+447700900002"
UNKNOWN_PHONE = "+447700900003"
MASKED_PHONE = "+44XXXXXX"

SMS_SENDER_HOOK = "mobile_otp_sms_sender"
SEND_OTP_PATH = "mobile_control.api.mobile_otp.send_token_via_sms"
PROVIDER_MODULE = "mobile_control.api.test_mobile_otp"

# Every call a custom SMS provider below received, in order. Cleared per test.
provider_calls: list[dict[str, Any]] = []


def sms_provider_ok(otp_secret: str, token: int | None = None, phone_no: str | None = None) -> bool:
	provider_calls.append({"otp_secret": otp_secret, "token": token, "phone_no": phone_no})
	return True


def sms_provider_rejects(otp_secret: str, token: int | None = None, phone_no: str | None = None) -> bool:
	provider_calls.append({"otp_secret": otp_secret, "token": token, "phone_no": phone_no})
	return False


@contextmanager
def _sms_providers(providers: list[str]) -> Iterator[None]:
	"""Pin the `mobile_otp_sms_sender` hook to `providers` for the duration.

	send_mobile_login_otp() prefers the last registered hook *over*
	send_token_via_sms. Without pinning it, these tests exercise whichever
	provider the site happens to have installed, the SEND_OTP_PATH patch is
	dead code on any site that registers one, and a real SMS goes out. Every
	other hook lookup is delegated to the real implementation untouched.
	"""
	real_get_hooks = frappe.get_hooks

	def fake_get_hooks(hook: str | None = None, *args: Any, **kwargs: Any) -> Any:
		if hook == SMS_SENDER_HOOK:
			return list(providers)
		return real_get_hooks(hook, *args, **kwargs)

	with patch.object(frappe, "get_hooks", side_effect=fake_get_hooks):
		yield


@contextmanager
def _mocked_sms(status: bool = True) -> Iterator[None]:
	"""No custom provider registered, and frappe's own SMS sender stubbed out."""
	with _sms_providers([]), patch(SEND_OTP_PATH, return_value=status):
		yield


def _set_mobile_login_enabled(value: Any) -> None:
	"""Toggle the OTP-login feature flag so the new value is visible in-process.

	SystemSettings.on_update() -> clear_system_settings_cache() clears redis and
	client_cache but not frappe.local.system_settings, which is the first thing
	frappe.get_system_settings() reads. Anything that touched System Settings
	earlier in the process (inserting a User does) leaves it populated, so
	without resetting it this save is invisible to is_mobile_otp_login_enabled()
	and the flag tests pass or fail for the wrong reason.
	"""
	settings = frappe.get_single("System Settings")
	settings.allow_login_using_mobile_number = value
	settings.save(ignore_permissions=True)
	frappe.local.system_settings = None


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

	SMS dispatch never leaves the process: each test pins the
	`mobile_otp_sms_sender` hook (to nothing, or to one of the fake providers
	above) and stubs frappe's own send_token_via_sms, so the dispatch path is
	the same whatever apps the site has installed.

	The OTP value is NOT the raw cached `_token`. That is an HOTP *counter*,
	generated via `pyotp.TOTP(secret).now()` purely to seed a fresh counter per
	request: frappe's send_token_via_sms computes the digits actually texted as
	`pyotp.HOTP(secret).at(int(counter))`, and `frappe.twofactor.confirm_otp_token`
	verifies the submitted OTP against that same derivation. `_otp_from_cache`
	reproduces it, so the "correct" OTP here is what a real device would show.
	"""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.mobile_user = _make_user(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE, mobile=True)
		cls.plain_user = _make_user(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE, mobile=False)

		cls._prior_mobile_login_setting = frappe.db.get_single_value(
			"System Settings", "allow_login_using_mobile_number"
		)
		_set_mobile_login_enabled(1)

		cls._prior_sms_gateway_url = frappe.db.get_single_value("SMS Settings", "sms_gateway_url")
		sms_settings = frappe.get_single("SMS Settings")
		sms_settings.sms_gateway_url = "https://sms.example.test/send"
		sms_settings.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls) -> None:
		_set_mobile_login_enabled(cls._prior_mobile_login_setting)

		sms_settings = frappe.get_single("SMS Settings")
		sms_settings.sms_gateway_url = cls._prior_sms_gateway_url
		sms_settings.save(ignore_permissions=True)

		# Manual commit is required here, and only here. LoginManager.fail()
		# commits, and the invalid-OTP and unknown-tmp_id tests both reach it,
		# so this class's System Settings and SMS Settings writes are already
		# on disk by now and no rollback can take them back. The restore above
		# cannot rely on one either: IntegrationTestCase registers _rollback_db
		# as a *class* cleanup, which runs after tearDownClass, so leaving the
		# restore uncommitted just rolls the restore itself back and strands
		# the site with this suite's values — OTP login left enabled against a
		# fake SMS gateway URL.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		super().tearDownClass()

	def setUp(self) -> None:
		super().setUp()
		provider_calls.clear()
		self._reset_response()

		# verify_mobile_otp constructs a MobileLoginManager, whose base
		# LoginManager.__init__ reads frappe.local.request.path outside its own
		# try/except — unset when a whitelisted method is called directly, which
		# is exactly how these tests call it. Stand in a minimal request so the
		# constructor (and post_login()'s cookie handling) has something to read.
		builder = EnvironBuilder(method="POST", path="/api/method/mobile_auth.verify_login_otp")
		frappe.local.request = Request(builder.get_environ())

		# That request also switches the @rate_limit decorator ON: it is skipped
		# only while frappe.request is falsy. It then builds its redis key as
		# ":".join([frappe.local.request_ip, ...]), and frappe.init() leaves
		# request_ip as None, so the very first endpoint call would die on
		# TypeError before reaching any assertion. The value is unique per test
		# because that key — and the login-attempt tracker keyed on the same ip —
		# live in redis, outlive the test rollback, and would otherwise pool
		# every test and every re-run inside the 10 minute window into a single
		# 50-request budget.
		self._prior_request_ip = getattr(frappe.local, "request_ip", None)
		frappe.local.request_ip = f"203.0.113.1/test-{frappe.generate_hash(length=12)}"

	def tearDown(self) -> None:
		self._reset_response()
		frappe.local.request = None
		frappe.local.request_ip = self._prior_request_ip

		# authenticate_with_otp() stamps otp/tmp_id onto the shared form_dict and
		# never clears them; left behind, a later test's plain
		# MobileLoginManager().authenticate(user, pwd) call would silently take
		# the OTP branch instead.
		for key in ("otp", "tmp_id"):
			frappe.form_dict.pop(key, None)
		frappe.set_user("Administrator")
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

	@staticmethod
	def _cache_str(key: str) -> str | None:
		# Must read back with the same raw, non-namespaced API
		# cache_mobile_otp_data() writes with (frappe.cache.pipeline().set(...)),
		# matching the existing nosemgrep precedent for this same OTP cache
		# contract in helpers/custom_login_manager.py.
		value = frappe.cache.get(key)  # nosemgrep
		if isinstance(value, bytes):
			value = value.decode("utf-8")
		return value

	def _otp_from_cache(self) -> tuple[str, str]:
		"""Return (tmp_id, otp) for the OTP the last send cached, where `otp` is
		the exact digits a real device would receive — not the cached counter."""
		tmp_id = frappe.local.response["tmp_id"]
		self.assertTrue(tmp_id)

		counter = self._cache_str(tmp_id + "_token")
		otp_secret = self._cache_str(tmp_id + "_otp_secret")
		self.assertIsNotNone(counter, "send_mobile_otp must cache an HOTP counter for verify to check")
		self.assertIsNotNone(otp_secret, "send_mobile_otp must cache the otp_secret for verify to check")

		return tmp_id, pyotp.HOTP(otp_secret).at(int(counter))

	def _send_otp(self, mobile_no: str) -> tuple[str, str]:
		with _mocked_sms():
			api_auth.send_mobile_otp(mobile_no)
		return self._otp_from_cache()

	# --- send_mobile_otp --------------------------------------------------

	def test_send_otp_returns_tmp_id_and_masks_mobile_no(self) -> None:
		tmp_id, _otp = self._send_otp(MOBILE_OTP_USER_PHONE)

		self.assertTrue(tmp_id)
		self.assertEqual(frappe.local.response["mobile_no"], MASKED_PHONE)
		# The TOTP secret must never leave the server in the response.
		self.assertNotIn("otp_secret", frappe.local.response)

	def test_send_otp_unknown_mobile_number_is_rejected(self) -> None:
		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.send_mobile_otp(UNKNOWN_PHONE)
		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertNotIn("tmp_id", frappe.local.response)

	def test_send_otp_dispatch_failure_raises(self) -> None:
		with _mocked_sms(status=False):
			with self.assertRaises(frappe.AuthenticationError) as cm:
				api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)
		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertNotIn("tmp_id", frappe.local.response)

	def test_send_otp_rejected_when_feature_disabled(self) -> None:
		_set_mobile_login_enabled(0)
		try:
			# SMS is stubbed too, defensively: if the setting failed to take
			# effect this must fail on the setting check, never on a real call
			# to the (fake) gateway URL.
			with _mocked_sms():
				with self.assertRaises(frappe.AuthenticationError) as cm:
					api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)
			self.assertEqual(cm.exception.http_status_code, 401)
			self.assertNotIn("tmp_id", frappe.local.response)
		finally:
			_set_mobile_login_enabled(1)

	# --- custom SMS providers (mobile_otp_sms_sender hook) ----------------

	def test_custom_sms_provider_is_used_instead_of_default_sender(self) -> None:
		with _sms_providers([f"{PROVIDER_MODULE}.sms_provider_ok"]):
			with patch(SEND_OTP_PATH) as default_sender:
				api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)

		default_sender.assert_not_called()
		self.assertEqual(len(provider_calls), 1)

		call = provider_calls[0]
		self.assertEqual(call["phone_no"], MOBILE_OTP_USER_PHONE)
		self.assertTrue(call["otp_secret"])
		# A provider is handed the HOTP counter, not the digits, and derives the
		# message itself exactly as frappe's own send_token_via_sms does. If this
		# drifts, custom providers start texting codes that never verify.
		_tmp_id, otp = self._otp_from_cache()
		self.assertEqual(pyotp.HOTP(call["otp_secret"]).at(int(call["token"])), otp)

	def test_custom_sms_provider_rejection_is_a_dispatch_failure(self) -> None:
		with _sms_providers([f"{PROVIDER_MODULE}.sms_provider_rejects"]):
			with self.assertRaises(frappe.AuthenticationError) as cm:
				api_auth.send_mobile_otp(MOBILE_OTP_USER_PHONE)

		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertEqual(len(provider_calls), 1)
		self.assertNotIn("tmp_id", frappe.local.response)

	# --- verify_mobile_otp --------------------------------------------------

	def test_verify_otp_completes_login_with_tokens_at_top_level(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_PHONE)
		self._reset_response()

		result = api_auth.verify_mobile_otp(tmp_id, otp)

		# Mirrors test_refresh_token.py's regression guard: the endpoint writes
		# straight to frappe.local.response, so Frappe does not wrap the payload
		# under `message`.
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
		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.verify_mobile_otp(tmp_id, otp)
		self.assertEqual(cm.exception.http_status_code, 401)

	def test_invalid_otp_is_rejected(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_PHONE)
		self._reset_response()
		wrong_otp = "".join("1" if digit != "1" else "2" for digit in otp)
		self.assertNotEqual(wrong_otp, otp)

		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.verify_mobile_otp(tmp_id, wrong_otp)
		self.assertEqual(cm.exception.http_status_code, 401)

	def test_verify_otp_user_without_mobile_role_is_rejected(self) -> None:
		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()

		with self.assertRaises(frappe.PermissionError) as cm:
			api_auth.verify_mobile_otp(tmp_id, otp)
		self.assertEqual(cm.exception.http_status_code, 403)

	def test_verify_otp_missing_params_returns_417(self) -> None:
		with self.assertRaises(frappe.ValidationError) as cm:
			api_auth.verify_mobile_otp("", "")
		self.assertEqual(cm.exception.http_status_code, 417)

	def test_verify_otp_unknown_tmp_id_is_rejected(self) -> None:
		with self.assertRaises(frappe.AuthenticationError) as cm:
			api_auth.verify_mobile_otp("does-not-exist", "123456")
		self.assertEqual(cm.exception.http_status_code, 401)
