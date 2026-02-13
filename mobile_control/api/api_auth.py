# mobile_control/api/api_auth.py

"""Mobile authentication API endpoints."""

from typing import Any

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import validate_phone_number

from .helpers.constants import get_mobile_login_ratelimit
from .helpers.constants import get_mobile_otp_ratelimit
from .helpers.mobile_config import get_mobile_configuration_payload
from .helpers.permissions import get_user_permissions as get_user_permissions_data
from .helpers.refresh_token import create_refresh_token
from .helpers.refresh_token import get_valid_refresh_token_doc
from .helpers.refresh_token import revoke_refresh_tokens_for_user
from .helpers.refresh_token import rotate_refresh_token
from .helpers.response_builder import build_auth_response
from .helpers.response_builder import clear_login_response
from .helpers.response_builder import get_request_metadata
from .helpers.user_auth import authenticate_user
from .helpers.user_auth import authenticate_with_otp
from .helpers.user_auth import ensure_api_credentials
from .helpers.user_auth import generate_auth_token
from .helpers.user_auth import generate_user_token
from .helpers.user_auth import validate_mobile_user_role
from .helpers.user_auth import validate_mobile_user_role_for_user
from .mobile_otp import find_user_by_mobile
from .mobile_otp import is_mobile_otp_login_enabled
from .mobile_otp import send_mobile_login_otp


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_mobile_configuration() -> list[dict[str, Any]]:
	"""Guest API to fetch mobile configuration list."""
	return get_mobile_configuration_payload().get("configuration", [])


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_mobile_app_status() -> dict[str, Any]:
	"""Guest API to fetch mobile app status and details."""
	payload = get_mobile_configuration_payload()
	return {
		"enabled": payload["enabled"],
		"package_name": payload["package_name"],
		"app_title": payload["app_title"],
		"version": payload["version"],
	}


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=get_mobile_login_ratelimit, seconds=60 * 60)
def login(username: str | None = None, password: str | None = None) -> None:
	"""Mobile app login handler."""
	try:
		user = authenticate_user(username, password)
		validate_mobile_user_role()
		ensure_api_credentials(user)
		access_token = generate_auth_token(user)
		device_id, user_agent = get_request_metadata()
		refresh_token = create_refresh_token(user, device_id=device_id, user_agent=user_agent)

		frappe.local.login_manager.logout()
		clear_login_response()

		mobile_config = get_mobile_configuration_payload().get("configuration", [])

		frappe.local.response.update(
			build_auth_response(
				user,
				access_token,
				refresh_token=refresh_token,
				mobile_config=mobile_config,
			)
		)

	except frappe.PermissionError:
		frappe.throw(_("Not allowed to use mobile app"))
	except Exception as e:
		frappe.log_error(f"Mobile Login Error: {e}")
		frappe.throw(_("Unable to login"))


@frappe.whitelist(methods=["POST"])
def logout() -> dict[str, str]:
	"""Mobile app logout handler."""
	try:
		user = frappe.get_doc("User", frappe.session.user)
		revoke_refresh_tokens_for_user(user)
		user.api_key = None
		user.api_secret = None
		user.save(ignore_permissions=True)
		return {"message": _("Logged out successfully")}
	except Exception as e:
		frappe.log_error(f"Mobile Logout Error: {e}")
		frappe.throw(_("Unable to logout"))


def _validate_mobile_otp_prerequisites() -> None:
	"""Validate mobile OTP prerequisites."""
	if not is_mobile_otp_login_enabled():
		frappe.throw(_("Mobile OTP login is not enabled"), frappe.AuthenticationError)

	sms_gateway_url = frappe.get_cached_value("SMS Settings", "SMS Settings", "sms_gateway_url")
	if not sms_gateway_url:
		frappe.throw(_("SMS Settings are not configured"), frappe.AuthenticationError)


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="mobile_no", limit=get_mobile_otp_ratelimit, seconds=60 * 10)
def send_mobile_otp(mobile_no: str) -> dict[str, str]:
	"""Send mobile OTP for authentication."""
	try:
		_validate_mobile_otp_prerequisites()
		validate_phone_number(mobile_no, throw=True)
		user_data = find_user_by_mobile(mobile_no)
		result = send_mobile_login_otp(user_data.name, mobile_no)
		return {
			"message": _("OTP sent successfully"),
			"tmp_id": result.get("tmp_id"),
			"mobile_no": result.get("mobile_no"),
			"prompt": _("Enter verification code sent to {0}").format(result.get("mobile_no", "******")),
		}

	except frappe.AuthenticationError:
		frappe.throw(_("Authentication failed"))
	except frappe.ValidationError:
		frappe.throw(_("Invalid mobile number"))
	except Exception as e:
		frappe.log_error(f"Mobile OTP Send Error: {e}")
		frappe.throw(_("Failed to send OTP. Please try again."))


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="tmp_id", limit=get_mobile_otp_ratelimit, seconds=60 * 10)
def verify_mobile_otp(tmp_id: str, otp: str) -> None:
	"""Verify OTP and complete login."""
	try:
		if not tmp_id or not otp:
			frappe.throw(_("OTP and temporary ID are required"), frappe.ValidationError)

		login_manager = authenticate_with_otp(otp, tmp_id)
		validate_mobile_user_role()
		user_doc, access_token = generate_user_token(login_manager)
		device_id, user_agent = get_request_metadata()
		refresh_token = create_refresh_token(user_doc, device_id=device_id, user_agent=user_agent)
		login_manager.logout()

		clear_login_response()

		mobile_config = get_mobile_configuration_payload().get("configuration", [])

		frappe.local.response.update(
			build_auth_response(
				user_doc,
				access_token,
				refresh_token=refresh_token,
				mobile_config=mobile_config,
			)
		)

	except frappe.AuthenticationError:
		frappe.throw(_("Invalid OTP or session expired"))
	except frappe.ValidationError:
		frappe.throw(_("Invalid request parameters"))
	except Exception as e:
		frappe.log_error(f"Mobile OTP Verify Error: {e}")
		frappe.throw(_("Failed to verify OTP. Please try again."))


# nosemgrep frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="refresh_token", limit=get_mobile_login_ratelimit, seconds=60 * 60)
def refresh_token(refresh_token: str) -> dict[str, str]:
	"""Refresh access token using refresh token."""
	try:
		token_doc = get_valid_refresh_token_doc(refresh_token)
		user_doc = frappe.get_doc("User", token_doc["user"])
		validate_mobile_user_role_for_user(user_doc)
		ensure_api_credentials(user_doc)
		access_token = generate_auth_token(user_doc)
		new_refresh_token = rotate_refresh_token(token_doc, user_doc)

		return build_auth_response(
			user_doc,
			access_token,
			refresh_token=new_refresh_token,
			message=_("Token refreshed"),
		)
	except frappe.AuthenticationError:
		frappe.throw(_("Invalid or expired refresh token"))
	except frappe.PermissionError:
		frappe.throw(_("Not allowed to use mobile app"))
	except frappe.ValidationError:
		frappe.throw(_("Invalid request parameters"))
	except Exception as e:
		frappe.log_error(f"Mobile Refresh Token Error: {e}")
		frappe.throw(_("Failed to refresh token. Please try again."))


@frappe.whitelist(methods=["GET"])
def get_user_permissions() -> dict[str, Any]:
	"""Get current user permissions including roles and doctype permissions."""
	try:
		user = frappe.get_doc("User", frappe.session.user)
		return get_user_permissions_data(user)
	except Exception as e:
		frappe.log_error(f"Error fetching user permissions: {e}")
		frappe.throw(_("Failed to fetch permissions"))
