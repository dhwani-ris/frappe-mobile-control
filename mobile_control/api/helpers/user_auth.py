# mobile_control/api/helpers/user_auth.py

"""User authentication and validation helpers."""

import secrets
from typing import Any

import frappe
from frappe import _
from frappe.auth import LoginManager

from ..jwt_auth import encode_api_credentials
from .constants import ACCESS_TOKEN_TTL_SECONDS
from .constants import MOBILE_USER_ROLES
from .custom_login_manager import MobileLoginManager


def authenticate_user(username: str | None, password: str | None) -> Any:
	"""Authenticate user using custom login manager."""
	login_manager = MobileLoginManager()
	login_manager.authenticate(username, password)
	login_manager.post_login()
	return frappe.get_doc("User", frappe.session.user)


def validate_mobile_user_role() -> None:
	"""Validate if current user has mobile user role."""
	roles = frappe.get_roles()
	if not set(MOBILE_USER_ROLES).intersection(roles):
		raise frappe.PermissionError(_("User is not allowed to use mobile app"))


def validate_mobile_user_role_for_user(user: Any) -> None:
	"""Validate if a user has mobile user role."""
	roles = frappe.get_roles(user.name)
	if not set(MOBILE_USER_ROLES).intersection(roles):
		raise frappe.PermissionError(_("User is not allowed to use mobile app"))


def ensure_api_credentials(user: Any) -> None:
	"""Generate API credentials if not exists."""
	if not user.api_key or not user.get_password("api_secret"):
		user.api_key = secrets.token_urlsafe(16)
		user.api_secret = secrets.token_urlsafe(32)
		user.save(ignore_permissions=True)


def generate_auth_token(user: Any, expires_in: int = ACCESS_TOKEN_TTL_SECONDS) -> str:
	"""Generate encrypted authentication token."""
	api_secret = user.get_password("api_secret")
	return encode_api_credentials(user.api_key, api_secret, expires_in=expires_in)


def authenticate_with_otp(otp: str, tmp_id: str) -> MobileLoginManager:
	"""Authenticate user with OTP and return login manager."""
	# Set form_dict for compatibility with authenticate method
	frappe.form_dict["otp"] = otp
	frappe.form_dict["tmp_id"] = tmp_id

	login_manager = MobileLoginManager()
	login_manager._authenticate_mobile_otp(otp, tmp_id)
	login_manager.post_login()
	return login_manager


def generate_user_token(login_manager: MobileLoginManager) -> tuple[Any, str]:
	"""Generate API credentials and token for authenticated user."""
	user_doc = frappe.get_doc("User", login_manager.user)
	ensure_api_credentials(user_doc)
	access_token = generate_auth_token(user_doc)
	return user_doc, access_token
