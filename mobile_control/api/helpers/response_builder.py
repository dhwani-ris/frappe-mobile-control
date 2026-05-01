# mobile_control/api/helpers/response_builder.py

"""Response building helpers."""

from typing import Any

import frappe
from frappe import _

from .mobile_config import get_mobile_configuration_payload
from .permissions import get_user_permissions


def clear_login_response() -> None:
	"""Clear unwanted fields set by post_login()."""
	frappe.local.response.pop("message", None)
	frappe.local.response.pop("home_page", None)
	frappe.response.pop("full_name", None)


def build_auth_response(
	user: Any,
	access_token: str,
	refresh_token: str | None = None,
	mobile_config: list[dict[str, Any]] | None = None,
	message: str | None = None,
	include_permissions: bool = True,
	offline_enabled: bool = False,
) -> dict[str, Any]:
	"""Build authentication response with tokens and user data."""
	user_lang = (
		getattr(user, "language", None) or frappe.db.get_value("User", user.name, "language") or ""
	).strip() or "en"
	response = {
		"message": message or _("Logged In"),
		"user": user.name,
		"full_name": user.full_name,
		"language": user_lang,
		"access_token": access_token,
		"offline_enabled": bool(offline_enabled),
	}
	if refresh_token:
		response["refresh_token"] = refresh_token
	if mobile_config is not None:
		response["mobile_form_names"] = mobile_config
	if include_permissions:
		perms = get_user_permissions(user)
		response["roles"] = perms["roles"]
		response["permissions"] = perms["permissions"]
	return response


def build_otp_response(tmp_id: str, mobile_no: str) -> dict[str, Any]:
	"""Build OTP response with tmp_id and mobile_no."""
	response = {
		"message": _("OTP sent successfully"),
		"tmp_id": tmp_id,
		"mobile_no": mobile_no,
		"prompt": _("Enter verification code sent to {0}").format(mobile_no, "******"),
	}
	return response


def get_request_metadata() -> tuple[str | None, str | None]:
	"""Get device_id and user_agent from request."""
	device_id = frappe.form_dict.get("device_id")
	user_agent = frappe.get_request_header("User-Agent")
	return device_id, user_agent
