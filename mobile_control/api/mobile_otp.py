# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
import pyotp
from frappe import _
from frappe.auth import get_login_attempt_tracker
from frappe.twofactor import get_otpsecret_for_
from frappe.twofactor import send_token_via_sms
from frappe.utils import cint


def is_mobile_otp_login_enabled() -> bool:
	"""Return True if login via mobile number and OTP is enabled in system settings."""
	return cint(frappe.get_system_settings("allow_login_using_mobile_number"))
	# and cint(
	# 	frappe.get_system_settings("allow_mobile_login_with_otp")
	# )


def validate_mobile_otp_prerequisites() -> None:
	"""Ensure mobile OTP login is enabled and SMS gateway is configured. Raises AuthenticationError if not."""
	if not is_mobile_otp_login_enabled():
		frappe.throw(_("Phone OTP login is not enabled."), frappe.AuthenticationError)

	sms_gateway_url = frappe.get_cached_value("SMS Settings", "SMS Settings", "sms_gateway_url")
	if not sms_gateway_url:
		frappe.throw(
			_("SMS Settings are not configured. Please contact administrator."), frappe.AuthenticationError
		)


def find_user_by_mobile(mobile_no: str) -> dict[str, str]:
	"""Look up an enabled User by mobile_no. Returns dict with name and mobile_no. Raises on invalid/missing."""
	if not mobile_no:
		frappe.throw(_("Phone number is required."), frappe.ValidationError)

	user = frappe.db.get_value(
		"User", {"mobile_no": mobile_no, "enabled": 1}, ["name", "mobile_no"], as_dict=True
	)

	if not user:
		if ip_tracker := get_login_attempt_tracker(frappe.local.request_ip, raise_locked_exception=False):
			ip_tracker.add_failure_attempt()
		frappe.throw(_("No user found with this Phone number."), frappe.AuthenticationError)

	return user


def generate_mobile_otp(user: str) -> tuple[int, str]:
	"""Generate a TOTP token for the user. Returns (current_token, otp_secret)."""
	otp_secret = get_otpsecret_for_(user)
	token = int(pyotp.TOTP(otp_secret).now())

	return token, otp_secret


def cache_mobile_otp_data(user: str, token: int, otp_secret: str, tmp_id: str) -> None:
	"""Store OTP token, user and otp_secret in cache keyed by tmp_id for verification. Uses token_expiry or 300s."""
	pipeline = frappe.cache.pipeline()

	expiry_time = frappe.flags.token_expiry or 300
	pipeline.set(tmp_id + "_token", token, expiry_time)

	user = str(user) if user else ""
	otp_secret = str(otp_secret) if otp_secret else ""

	for k, v in {"_usr": user, "_otp_secret": otp_secret}.items():
		pipeline.set(f"{tmp_id}{k}", v, expiry_time)
	pipeline.execute()


def send_mobile_login_otp(user: str, mobile_no: str) -> dict[str, str]:
	"""Validate settings, generate OTP, cache it, send via SMS (or hook). Returns message, tmp_id, masked mobile_no."""
	from frappe.model.utils.mask import mask_field_value

	validate_mobile_otp_prerequisites()

	token, otp_secret = generate_mobile_otp(user)

	tmp_id = frappe.generate_hash(length=8)

	cache_mobile_otp_data(user, token, otp_secret, tmp_id)

	hook_methods = frappe.get_hooks("mobile_otp_sms_sender")
	if hook_methods:
		status = frappe.get_attr(hook_methods[-1])(otp_secret, token=token, phone_no=mobile_no)
	else:
		status = send_token_via_sms(otp_secret, token=token, phone_no=mobile_no)

	if not status:
		frappe.throw(_("Failed to send OTP. Please try again."), frappe.AuthenticationError)

	return {
		"message": _("OTP sent successfully"),
		"tmp_id": tmp_id,
		"mobile_no": mask_field_value(frappe.get_meta("User").get_field("mobile_no"), mobile_no),
	}
