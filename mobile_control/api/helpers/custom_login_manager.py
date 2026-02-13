# mobile_control/api/helpers/custom_login_manager.py

"""Custom LoginManager with mobile OTP authentication support."""

import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.auth import get_login_attempt_tracker
from frappe.core.doctype.user.user import User

# Maximum password size constant (from Frappe core)
MAX_PASSWORD_SIZE = 100


class MobileLoginManager(LoginManager):
	"""Extended LoginManager with mobile OTP authentication support."""

	def _authenticate_mobile_otp(self, otp: str, tmp_id: str) -> None:
		"""Authenticate user using mobile OTP."""
		from frappe.twofactor import confirm_otp_token

		# Get cached user from tmp_id
		cached_user = frappe.cache.get(tmp_id + "_usr")
		if not cached_user:
			self.fail(_("Login session expired. Please try again."))

		if isinstance(cached_user, bytes):
			cached_user = cached_user.decode("utf-8")

		self.user = cached_user
		if not confirm_otp_token(self, otp=otp, tmp_id=tmp_id):
			self.user = None
			self.fail(_("Invalid OTP. Please try again."))

	def authenticate(self, user: str | None = None, pwd: str | None = None) -> None:
		"""Override authenticate to support mobile OTP authentication."""
		form_user, form_pwd = frappe.form_dict.get("usr"), frappe.form_dict.get("pwd")
		otp, tmp_id = frappe.form_dict.get("otp"), frappe.form_dict.get("tmp_id")

		# Handle mobile OTP authentication
		if (otp and tmp_id) and not (form_user and form_pwd):
			self._authenticate_mobile_otp(otp, tmp_id)
			return

		# Fall back to standard authentication
		if not (user and pwd):
			user, pwd = form_user, form_pwd
		if not (user and pwd):
			self.fail(_("Incomplete login details"), user=user)

		if len(pwd) > MAX_PASSWORD_SIZE:
			self.fail(_("Password size exceeded the maximum allowed size"), user=user)

		_raw_user_name = user
		user = User.find_by_credentials(user, pwd)

		ip_tracker = get_login_attempt_tracker(frappe.local.request_ip)
		if not user:
			ip_tracker and ip_tracker.add_failure_attempt()
			self.fail("Invalid login credentials", user=_raw_user_name)

		# Current login flow uses cached credentials for authentication while checking OTP.
		# In case of OTP check, tracker for auth needs to be disabled
		# (If not, it can remove tracker history as it is going to succeed anyway)
		# Tracker is activated for 2FA in case of OTP.
		from frappe.twofactor import should_run_2fa

		ignore_tracker = should_run_2fa(user.name) and ("otp" in frappe.form_dict)
		user_tracker = None if ignore_tracker else get_login_attempt_tracker(user.name)

		if not user.is_authenticated:
			user_tracker and user_tracker.add_failure_attempt()
			ip_tracker and ip_tracker.add_failure_attempt()
			self.fail("Invalid login credentials", user=user.name)
		elif not (user.name == "Administrator" or user.enabled):
			user_tracker and user_tracker.add_failure_attempt()
			ip_tracker and ip_tracker.add_failure_attempt()
			self.fail("User disabled or missing", user=user.name)
		else:
			user_tracker and user_tracker.add_success_attempt()
			ip_tracker and ip_tracker.add_success_attempt()
		self.user = user.name
