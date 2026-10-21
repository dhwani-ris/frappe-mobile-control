from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import frappe
import pyotp
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request
from mobile_control.api import api_auth
from mobile_control.api import mobile_otp
from mobile_control.api.helpers.custom_login_manager import MobileLoginManager
from mobile_control.api.helpers.user_auth import ensure_api_credentials

MOBILE_OTP_USER_EMAIL = "otp-session@example.com"
MOBILE_OTP_USER_PHONE = "9876500011"
NON_MOBILE_OTP_USER_EMAIL = "otp-session-plain@example.com"
NON_MOBILE_OTP_USER_PHONE = "9876500012"

SEND_OTP_PATH = "mobile_control.api.mobile_otp.send_token_via_sms"

PROVIDER_MODULE = "mobile_control.api.test_mobile_otp"

#: Every call a module-level fake provider receives, in order, as
#: (provider_name, otp_secret, token, phone_no). Cleared in setUp.
PROVIDER_CALLS: list[tuple[str, str, int, str]] = []


# --- module-level fake SMS providers -------------------------------------
# These must be importable by dotted path, because `frappe.get_attr` is what
# resolves a `mobile_otp_sms_sender` hook in production.


def sms_provider_ok(otp_secret: str, token: int, phone_no: str) -> bool:
	"""A provider that dispatches successfully."""
	PROVIDER_CALLS.append(("ok", otp_secret, token, phone_no))
	return True


def sms_provider_rejects(otp_secret: str, token: int, phone_no: str) -> bool:
	"""A provider that declines the send without raising."""
	PROVIDER_CALLS.append(("rejects", otp_secret, token, phone_no))
	return False


def sms_provider_raises(otp_secret: str, token: int, phone_no: str) -> bool:
	"""A provider that blows up mid-dispatch, as a real gateway client can."""
	PROVIDER_CALLS.append(("raises", otp_secret, token, phone_no))
	raise RuntimeError("gateway timed out")


@contextmanager
def _sms_providers(*dotted_paths: str) -> Iterator[None]:
	"""Pin the `mobile_otp_sms_sender` hook to exactly `dotted_paths`.

	Patching `frappe.get_hooks` wholesale would break every other hook lookup
	Frappe makes while a document is saved, so this intercepts only this one
	hook and delegates everything else to the real implementation. With no
	arguments it pins the hook to empty, which is how the "no custom provider
	registered" branch is exercised on a site that may legitimately have one
	installed.
	"""
	real_get_hooks = frappe.get_hooks
	hooked = list(dotted_paths)

	def fake_get_hooks(hook=None, *args, **kwargs):
		if hook == "mobile_otp_sms_sender":
			return list(hooked)
		return real_get_hooks(hook, *args, **kwargs)

	with patch.object(frappe, "get_hooks", side_effect=fake_get_hooks):
		yield


def _set_mobile_login_enabled(value: int | None) -> None:
	"""Flip `allow_login_using_mobile_number` and drop the cached singleton.

	`frappe.get_system_settings` reads `frappe.local.system_settings`, which is
	populated once per request; saving the DocType alone leaves the stale copy
	in place and the new value never takes effect inside the same test run.
	"""
	settings = frappe.get_single("System Settings")
	settings.allow_login_using_mobile_number = value
	settings.save(ignore_permissions=True)
	frappe.local.system_settings = frappe._dict()


_request_ip_counter = 0


def _unique_request_ip() -> str:
	"""A fresh IP per test, so login-attempt trackers and rate-limit counters
	from one test cannot lock out the next."""
	global _request_ip_counter
	_request_ip_counter += 1
	return f"127.0.{_request_ip_counter // 256 % 256}.{_request_ip_counter % 256}"


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


class TestMobileOtpSmsProviders(IntegrationTestCase):
	"""`mobile_otp.send_mobile_login_otp` dispatch through a custom provider.

	A `mobile_otp_sms_sender` hook is third-party code. It can return False,
	it can raise, and its dotted path can go stale and stop resolving. All
	three are the same thing to a caller — the OTP did not go out — so all
	three must produce the same AuthenticationError (401). Before the fix only
	the False case did: a raising provider, or an unresolvable path, escaped
	`send_mobile_login_otp` entirely and surfaced from the endpoint's generic
	handler as a 417 "malformed request", with nothing in the logs naming the
	provider that broke.

	These tests call `send_mobile_login_otp` directly rather than through
	`api_auth.send_mobile_otp`, so they assert the dispatch contract itself
	and not the endpoint's exception mapping (which is covered elsewhere).
	"""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.mobile_user = _make_user(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE, mobile=True)

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
		super().tearDownClass()

	def setUp(self) -> None:
		super().setUp()
		PROVIDER_CALLS.clear()
		# `find_user_by_mobile` and the login-attempt trackers key off the
		# request IP; a unique one per test keeps counters from one test
		# locking out the next.
		frappe.local.request_ip = _unique_request_ip()

	def tearDown(self) -> None:
		PROVIDER_CALLS.clear()
		frappe.set_user("Administrator")
		super().tearDown()

	def _send(self) -> dict[str, str]:
		return mobile_otp.send_mobile_login_otp(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE)

	# --- the failure modes all collapse to one status ---------------------

	def test_provider_that_returns_false_is_a_send_failure(self) -> None:
		"""The already-working case, pinned so the other two can be compared to it."""
		with _sms_providers(f"{PROVIDER_MODULE}.sms_provider_rejects"):
			with self.assertRaises(frappe.AuthenticationError) as cm:
				self._send()
		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertEqual([call[0] for call in PROVIDER_CALLS], ["rejects"])

	def test_provider_that_raises_is_a_send_failure_not_a_bad_request(self) -> None:
		with _sms_providers(f"{PROVIDER_MODULE}.sms_provider_raises"):
			with patch.object(frappe, "log_error") as log_error:
				with self.assertRaises(frappe.AuthenticationError) as cm:
					self._send()

		# Regression guard: this used to be the provider's own RuntimeError
		# escaping, which the endpoint reported as 417.
		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertEqual([call[0] for call in PROVIDER_CALLS], ["raises"])

		# The failure must leave a trail naming the provider, otherwise a
		# broken hook is indistinguishable from a provider declining.
		log_error.assert_called_once()
		logged = log_error.call_args.kwargs.get("message", "")
		self.assertIn("sms_provider_raises", logged)
		self.assertIn("gateway timed out", logged)

	def test_unresolvable_provider_path_is_a_send_failure(self) -> None:
		"""A hook left pointing at a renamed/removed function must not 417 either."""
		stale_path = f"{PROVIDER_MODULE}.sms_provider_that_no_longer_exists"
		with _sms_providers(stale_path):
			with patch.object(frappe, "log_error") as log_error:
				with self.assertRaises(frappe.AuthenticationError) as cm:
					self._send()

		self.assertEqual(cm.exception.http_status_code, 401)
		self.assertEqual(PROVIDER_CALLS, [])
		log_error.assert_called_once()
		self.assertIn(stale_path, log_error.call_args.kwargs.get("message", ""))

	# --- the paths that must keep working ---------------------------------

	def test_successful_provider_sends_and_returns_tmp_id(self) -> None:
		with _sms_providers(f"{PROVIDER_MODULE}.sms_provider_ok"):
			result = self._send()

		self.assertTrue(result["tmp_id"])
		self.assertEqual(result["mobile_no"], "987XXXXXX")
		self.assertEqual([call[0] for call in PROVIDER_CALLS], ["ok"])

		# The provider is handed the same arguments as before the refactor:
		# positional secret, keyword token and phone_no.
		_name, otp_secret, token, phone_no = PROVIDER_CALLS[0]
		self.assertEqual(phone_no, MOBILE_OTP_USER_PHONE)
		self.assertTrue(otp_secret)
		self.assertIsInstance(token, int)

	def test_last_registered_provider_wins(self) -> None:
		"""Several apps may hook the sender; the last one registered is the one used."""
		with _sms_providers(
			f"{PROVIDER_MODULE}.sms_provider_rejects",
			f"{PROVIDER_MODULE}.sms_provider_ok",
		):
			result = self._send()
		self.assertTrue(result["tmp_id"])
		self.assertEqual([call[0] for call in PROVIDER_CALLS], ["ok"])

		PROVIDER_CALLS.clear()

		# Reversed, the same two hooks must fail — proving it is the last
		# entry being picked and not merely "any successful provider".
		with _sms_providers(
			f"{PROVIDER_MODULE}.sms_provider_ok",
			f"{PROVIDER_MODULE}.sms_provider_rejects",
		):
			with self.assertRaises(frappe.AuthenticationError):
				self._send()
		self.assertEqual([call[0] for call in PROVIDER_CALLS], ["rejects"])

	def test_default_sms_sender_is_used_when_no_provider_is_hooked(self) -> None:
		"""The untouched branch: no hook means frappe's own sender, unwrapped."""
		with _sms_providers():
			with patch(SEND_OTP_PATH, return_value=True) as send_token:
				result = self._send()

		self.assertTrue(result["tmp_id"])
		send_token.assert_called_once()
		self.assertEqual(PROVIDER_CALLS, [])

	def test_default_sms_sender_failure_still_raises(self) -> None:
		with _sms_providers():
			with patch(SEND_OTP_PATH, return_value=False):
				with self.assertRaises(frappe.AuthenticationError) as cm:
					self._send()
		self.assertEqual(cm.exception.http_status_code, 401)

	def test_default_sms_sender_exception_is_not_swallowed(self) -> None:
		"""The guard is scoped to hooked providers; frappe's own sender is
		first-party code and its failures must keep propagating as-is."""
		with _sms_providers():
			with patch(SEND_OTP_PATH, side_effect=RuntimeError("boom")):
				with self.assertRaises(RuntimeError):
					self._send()


class TestMobileOtpVerifySessionCleanup(IntegrationTestCase):
	"""`api_auth.verify_mobile_otp` must not leave a session behind on rejection.

	`authenticate_with_otp()` calls `post_login()`, which writes a real session
	row, and it does so *before* `validate_mobile_user_role()` gets to reject a
	user who lacks the Mobile User role. `login_manager.logout()` used to sit on
	the success path only, so a rejected user was correctly refused and still
	walked away with a live session that lasted until it expired on its own.
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
		super().tearDownClass()

	def setUp(self) -> None:
		super().setUp()
		self._reset_response()
		frappe.local.request_ip = _unique_request_ip()
		# `MobileLoginManager`'s base `LoginManager.__init__` reads
		# `frappe.request.path`, which `bench run-tests` does not set up when a
		# whitelisted method is called directly. Stand in a minimal request so
		# the constructor and `post_login()`'s cookie handling have something
		# to read.
		builder = EnvironBuilder(method="POST", path="/api/method/mobile_auth.verify_login_otp")
		frappe.local.request = Request(builder.get_environ())

	def tearDown(self) -> None:
		self._reset_response()
		frappe.local.request = None
		# `authenticate_with_otp()` stamps otp/tmp_id onto the shared form_dict
		# and never clears them; left behind, a later plain
		# `MobileLoginManager().authenticate(user, pwd)` would silently take
		# the OTP branch instead.
		frappe.form_dict.pop("otp", None)
		frappe.form_dict.pop("tmp_id", None)
		frappe.set_user("Administrator")
		super().tearDown()

	def _reset_response(self) -> None:
		for key in ("access_token", "refresh_token", "message", "tmp_id", "mobile_no", "prompt", "user"):
			frappe.local.response.pop(key, None)

	@staticmethod
	def _cache_str(key: str) -> str | None:
		# Read back with the same raw, non-namespaced API that
		# `cache_mobile_otp_data()` writes with, matching the existing
		# nosemgrep precedent for this OTP cache contract in
		# helpers/custom_login_manager.py.
		value = frappe.cache.get(key)  # nosemgrep
		if isinstance(value, bytes):
			value = value.decode("utf-8")
		return value

	def _send_otp(self, user_email: str, mobile_no: str) -> tuple[str, str]:
		"""Send an OTP (SMS mocked) and return (tmp_id, otp).

		`otp` is the digits a real device would receive, not the raw cached
		`_token`: that value is an HOTP *counter*, seeded per request via
		`pyotp.TOTP(secret).now()`. Frappe's `send_token_via_sms` texts
		`pyotp.HOTP(secret).at(counter)` and `confirm_otp_token` verifies
		against that same derivation, reproduced here.
		"""
		with _sms_providers():
			with patch(SEND_OTP_PATH, return_value=True):
				result = mobile_otp.send_mobile_login_otp(user_email, mobile_no)

		tmp_id = result["tmp_id"]
		counter = self._cache_str(tmp_id + "_token")
		otp_secret = self._cache_str(tmp_id + "_otp_secret")
		self.assertIsNotNone(counter, "send_mobile_login_otp must cache an HOTP counter")
		self.assertIsNotNone(otp_secret, "send_mobile_login_otp must cache the otp_secret")
		return tmp_id, pyotp.HOTP(otp_secret).at(int(counter))

	@staticmethod
	def _session_count(user_email: str) -> int:
		return frappe.db.count("Sessions", {"user": user_email})

	def _clear_sessions(self, user_email: str) -> None:
		frappe.db.delete("Sessions", {"user": user_email})

	# --- the leak ---------------------------------------------------------

	def test_rejected_user_is_left_without_a_session(self) -> None:
		self._clear_sessions(NON_MOBILE_OTP_USER_EMAIL)
		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()

		with self.assertRaises(Exception):
			api_auth.verify_mobile_otp(tmp_id, otp)

		# The endpoint already refused the user; the regression is that it
		# used to refuse them *and* hand them a working session, because
		# logout() sat on the success path only.
		self.assertEqual(
			self._session_count(NON_MOBILE_OTP_USER_EMAIL),
			0,
			"a user refused for lacking the Mobile User role must not keep a session",
		)

	def test_rejected_user_is_logged_out_exactly_once(self) -> None:
		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()

		with patch.object(MobileLoginManager, "logout", autospec=True) as logout:
			with self.assertRaises(Exception):
				api_auth.verify_mobile_otp(tmp_id, otp)
		self.assertEqual(logout.call_count, 1)

	def test_failing_logout_hook_does_not_mask_the_rejection(self) -> None:
		"""`LoginManager.logout()` runs every installed app's `on_logout` hooks.

		If one of them raises out of the `finally`, it would replace the
		exception being propagated and change the status the client sees. The
		rejection must come through unchanged, and the logout failure must be
		logged rather than raised.
		"""
		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()
		with self.assertRaises(Exception) as clean:
			api_auth.verify_mobile_otp(tmp_id, otp)
		expected_type = type(clean.exception)
		expected_status = getattr(clean.exception, "http_status_code", None)

		tmp_id, otp = self._send_otp(NON_MOBILE_OTP_USER_EMAIL, NON_MOBILE_OTP_USER_PHONE)
		self._reset_response()
		with patch.object(
			MobileLoginManager, "logout", autospec=True, side_effect=RuntimeError("on_logout hook blew up")
		):
			with patch.object(frappe, "log_error") as log_error:
				with self.assertRaises(Exception) as broken:
					api_auth.verify_mobile_otp(tmp_id, otp)

		self.assertIs(type(broken.exception), expected_type)
		self.assertEqual(getattr(broken.exception, "http_status_code", None), expected_status)
		self.assertNotIsInstance(broken.exception, RuntimeError)
		log_error.assert_called()

	# --- the success path must keep its ordering --------------------------

	def test_successful_login_still_logs_out_and_returns_tokens(self) -> None:
		self._clear_sessions(MOBILE_OTP_USER_EMAIL)
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE)
		self._reset_response()

		result = api_auth.verify_mobile_otp(tmp_id, otp)

		# Written straight to frappe.local.response, so Frappe does not wrap
		# the payload under `message`.
		self.assertIsNone(result)
		self.assertTrue(frappe.local.response.get("access_token"))
		self.assertTrue(frappe.local.response.get("refresh_token"))
		self.assertEqual(frappe.local.response.get("user"), MOBILE_OTP_USER_EMAIL)
		# logout() ran here before the fix too — the `finally` must not have
		# moved it after `clear_login_response()` or dropped it.
		self.assertEqual(self._session_count(MOBILE_OTP_USER_EMAIL), 0)

	def test_successful_login_calls_logout_exactly_once(self) -> None:
		tmp_id, otp = self._send_otp(MOBILE_OTP_USER_EMAIL, MOBILE_OTP_USER_PHONE)
		self._reset_response()

		with patch.object(MobileLoginManager, "logout", autospec=True) as logout:
			api_auth.verify_mobile_otp(tmp_id, otp)
		self.assertEqual(logout.call_count, 1)

	def test_failed_authentication_does_not_attempt_a_logout(self) -> None:
		"""`login_manager` is bound outside the try, so a failure inside
		`authenticate_with_otp()` must not reach the `finally` at all.

		Deliberately not asserting a status here: the endpoint currently
		re-throws an auth failure with a bare `frappe.throw`, which defaults to
		ValidationError (417). That remap is a separate pre-existing bug and is
		not this test's subject — what matters is that no logout is attempted
		on a name that was never bound.
		"""
		with patch.object(MobileLoginManager, "logout", autospec=True) as logout:
			with self.assertRaises(Exception):
				api_auth.verify_mobile_otp("does-not-exist", "123456")
		logout.assert_not_called()
