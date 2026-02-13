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
) -> dict[str, Any]:
	"""Build authentication response with tokens and user data."""
	response = {
		"message": message or _("Logged In"),
		"user": user.name,
		"full_name": user.full_name,
		"access_token": access_token,
	}
	if refresh_token:
		response["refresh_token"] = refresh_token
	if mobile_config is not None:
		response["mobile_form_names"] = mobile_config
	if include_permissions:
		response["permissions"] = get_user_permissions(user)
	return response


def get_request_metadata() -> tuple[str | None, str | None]:
	"""Get device_id and user_agent from request."""
	device_id = frappe.form_dict.get("device_id")
	user_agent = frappe.get_request_header("User-Agent")
	return device_id, user_agent
