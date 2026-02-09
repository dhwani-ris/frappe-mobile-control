# mobile_control/api/api_auth.py

import hashlib
import secrets
from typing import Any

import frappe
from frappe import _
from frappe.auth import LoginManager
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days
from frappe.utils import now_datetime
from frappe.utils import validate_phone_number

from .jwt_auth import encode_api_credentials

MOBILE_USER_ROLES = ["Mobile User"]
get_mobile_login_ratelimit = 50
get_mobile_otp_ratelimit = 50
ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24
REFRESH_TOKEN_TTL_DAYS = 30


def _authenticate_user(username: str | None, password: str | None) -> Any:
	"""Authenticate user using Frappe's login manager"""
	login_manager = LoginManager()
	login_manager.authenticate(username, password)
	login_manager.post_login()
	return frappe.get_doc("User", frappe.session.user)


def _validate_mobile_user_role() -> None:
	"""Validate if user has mobile user role"""
	roles = frappe.get_roles()
	if not set(MOBILE_USER_ROLES).intersection(roles):
		raise frappe.PermissionError(_("User is not allowed to use mobile app"))


def _validate_mobile_user_role_for_user(user: Any) -> None:
	"""Validate if a user has mobile user role"""
	roles = frappe.get_roles(user.name)
	if not set(MOBILE_USER_ROLES).intersection(roles):
		raise frappe.PermissionError(_("User is not allowed to use mobile app"))


def _ensure_api_credentials(user: Any) -> None:
	"""Generate API credentials if not exists"""
	if not user.api_key or not user.get_password("api_secret"):
		user.api_key = secrets.token_urlsafe(16)
		user.api_secret = secrets.token_urlsafe(32)
		user.save(ignore_permissions=True)


def _generate_auth_token(user: Any, expires_in: int = ACCESS_TOKEN_TTL_SECONDS) -> str:
	"""Generate encrypted authentication token"""
	api_secret = user.get_password("api_secret")
	return encode_api_credentials(user.api_key, api_secret, expires_in=expires_in)


def _hash_refresh_token(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


def _create_refresh_token(user: Any, device_id: str | None = None, user_agent: str | None = None) -> str:
	raw_token = secrets.token_urlsafe(32)
	token_hash = _hash_refresh_token(raw_token)
	refresh_doc = frappe.new_doc("Mobile Refresh Token")
	refresh_doc.user = user.name
	refresh_doc.token_hash = token_hash
	refresh_doc.expires_at = add_days(now_datetime(), REFRESH_TOKEN_TTL_DAYS)
	refresh_doc.revoked = 0
	refresh_doc.last_used = now_datetime()
	if device_id:
		refresh_doc.device_id = device_id
	if user_agent:
		refresh_doc.user_agent = user_agent
	refresh_doc.insert(ignore_permissions=True)
	return raw_token


def _get_valid_refresh_token_doc(refresh_token: str) -> dict[str, Any]:
	if not refresh_token:
		frappe.throw(_("Refresh token is required"), frappe.ValidationError)

	token_hash = _hash_refresh_token(refresh_token)
	token_docs = frappe.get_all(
		"Mobile Refresh Token",
		filters={"token_hash": token_hash, "revoked": 0},
		fields=["name", "user", "expires_at"],
		limit=1,
	)
	if not token_docs:
		raise frappe.AuthenticationError(_("Invalid refresh token"))

	token_doc = token_docs[0]
	if token_doc.get("expires_at") and now_datetime() > token_doc["expires_at"]:
		frappe.db.set_value(
			"Mobile Refresh Token",
			token_doc["name"],
			{"revoked": 1, "last_used": now_datetime()},
		)
		raise frappe.AuthenticationError(_("Refresh token expired"))

	return token_doc


def _rotate_refresh_token(token_doc: dict[str, Any], user: Any) -> str:
	frappe.db.set_value(
		"Mobile Refresh Token",
		token_doc["name"],
		{"revoked": 1, "last_used": now_datetime()},
	)
	return _create_refresh_token(user)


def _get_user_agent() -> str | None:
	return frappe.get_request_header("User-Agent")


def _get_device_id() -> str | None:
	return frappe.form_dict.get("device_id")


def _clear_login_response() -> None:
	# Clear unwanted fields set by post_login()
	frappe.local.response.pop("message", None)
	frappe.local.response.pop("home_page", None)
	frappe.response.pop("full_name", None)


def _get_mobile_configuration_payload() -> dict[str, Any]:
	"""Get mobile configuration and app status from Single doctype."""
	try:
		config = frappe.get_single("Mobile Configuration")
		configuration: list[dict[str, Any]] = []
		if config.table_lwis:
			for row in config.table_lwis:
				configuration.append(
					{
						"mobile_doctype": row.mobile_doctype,
						"group_name": row.group_name or "",
						"doctype_meta_modifed_at": row.doctype_meta_modifed_at or "",
						"doctype_icon": row.doctype_icon or "",
					}
				)
		enabled = bool(config.enabled)
		return {
			"enabled": enabled,
			"package_name": config.package_name if enabled else "",
			"app_title": config.app_name if enabled else "",
			"version": config.current_version if enabled else "",
			"configuration": configuration,
		}
	except Exception:
		return {
			"enabled": False,
			"package_name": "",
			"app_title": "",
			"version": "",
			"configuration": [],
		}


@frappe.whitelist(methods=["GET"])
def get_mobile_configuration() -> list[dict[str, Any]]:
	"""Guest API to fetch mobile configuration list."""
	return _get_mobile_configuration_payload().get("configuration", [])


@frappe.whitelist(allow_guest=True, methods=["GET"])  # no-semgrep
def get_mobile_app_status() -> dict[str, Any]:
	"""Guest API to fetch mobile app status and details."""
	payload = _get_mobile_configuration_payload()
	return {
		"enabled": payload["enabled"],
		"package_name": payload["package_name"],
		"app_title": payload["app_title"],
		"version": payload["version"],
	}


def _build_auth_response(
	user: Any,
	access_token: str,
	refresh_token: str | None = None,
	mobile_config: list[dict[str, Any]] | None = None,
	message: str | None = None,
) -> dict[str, Any]:
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
	return response


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=get_mobile_login_ratelimit, seconds=60 * 60)
def login(username: str | None = None, password: str | None = None) -> None:
	"""Mobile app login handler"""
	try:
		user = _authenticate_user(username, password)
		_validate_mobile_user_role()
		_ensure_api_credentials(user)
		access_token = _generate_auth_token(user)
		refresh_token = _create_refresh_token(user, device_id=_get_device_id(), user_agent=_get_user_agent())

		frappe.local.login_manager.logout()

		_clear_login_response()

		# Get mobile configuration
		mobile_config = _get_mobile_configuration_payload().get("configuration", [])

		frappe.local.response.update(
			_build_auth_response(
				user,
				access_token,
				refresh_token=refresh_token,
				mobile_config=mobile_config,
			)
		)

	# except frappe.AuthenticationError:
	# 	frappe.throw(_("Invalid username or password or user is not allowed to use mobile app"))
	except frappe.PermissionError:
		frappe.throw(_("Not allowed to use mobile app"))
	except Exception as e:
		frappe.log_error(f"Mobile Login Error: {e}")
		frappe.throw(_("Unable to login"))


@frappe.whitelist(methods=["POST"])
def logout() -> dict[str, str]:
	"""Mobile app logout handler"""
	try:
		user = frappe.get_doc("User", frappe.session.user)
		_revoke_refresh_tokens_for_user(user)
		user.api_key = None
		user.api_secret = None
		user.save(ignore_permissions=True)
		return {"message": _("Logged out successfully")}
	except Exception as e:
		frappe.log_error(f"Mobile Logout Error: {e}")
		frappe.throw(_("Unable to logout"))


def _validate_mobile_otp_prerequisites() -> None:
	"""Validate mobile OTP prerequisites"""
	from frappe.utils.mobile_otp import is_mobile_otp_login_enabled

	if not is_mobile_otp_login_enabled():
		frappe.throw(_("Mobile OTP login is not enabled"), frappe.AuthenticationError)

	sms_gateway_url = frappe.get_cached_value("SMS Settings", "SMS Settings", "sms_gateway_url")
	if not sms_gateway_url:
		frappe.throw(_("SMS Settings are not configured"), frappe.AuthenticationError)


def _find_user_by_mobile(mobile_no: str) -> dict[str, str]:
	"""Find user by mobile number"""
	from frappe.utils.mobile_otp import find_user_by_mobile

	if not mobile_no:
		frappe.throw(_("Mobile number is required"), frappe.ValidationError)

	return find_user_by_mobile(mobile_no)


def _send_otp_to_user(user_data: dict, mobile_no: str) -> dict[str, str]:
	"""Send OTP to user and return result"""
	from frappe.utils.mobile_otp import send_mobile_login_otp

	result = send_mobile_login_otp(user_data.name, mobile_no)
	return {
		"message": _("OTP sent successfully"),
		"tmp_id": result.get("tmp_id"),
		"mobile_no": result.get("mobile_no"),
		"prompt": _("Enter verification code sent to {0}").format(result.get("mobile_no", "******")),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="mobile_no", limit=get_mobile_otp_ratelimit, seconds=60 * 10)
def send_mobile_otp(mobile_no: str) -> dict[str, str]:
	"""Send mobile OTP for authentication"""
	try:
		_validate_mobile_otp_prerequisites()
		validate_phone_number(mobile_no, throw=True)
		user_data = _find_user_by_mobile(mobile_no)
		return _send_otp_to_user(user_data, mobile_no)

	except frappe.AuthenticationError:
		frappe.throw(_("Authentication failed"))
	except frappe.ValidationError:
		frappe.throw(_("Invalid mobile number"))
	except Exception as e:
		frappe.log_error(f"Mobile OTP Send Error: {e}")
		frappe.throw(_("Failed to send OTP. Please try again."))


def _authenticate_with_otp(otp: str, tmp_id: str) -> LoginManager:
	"""Authenticate user with OTP and return login manager"""
	login_manager = LoginManager()
	login_manager._authenticate_mobile_otp(otp, tmp_id)
	login_manager.post_login()
	return login_manager


def _generate_user_token(login_manager: LoginManager) -> tuple[Any, str]:
	"""Generate API credentials and token for authenticated user"""
	user_doc = frappe.get_doc("User", login_manager.user)
	_ensure_api_credentials(user_doc)
	access_token = _generate_auth_token(user_doc)
	return user_doc, access_token


def _revoke_refresh_tokens_for_user(user: Any) -> None:
	token_names = frappe.get_all(
		"Mobile Refresh Token",
		filters={"user": user.name, "revoked": 0},
		pluck="name",
	)
	for token_name in token_names:
		frappe.db.set_value(
			"Mobile Refresh Token",
			token_name,
			{"revoked": 1, "last_used": now_datetime()},
		)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="tmp_id", limit=get_mobile_otp_ratelimit, seconds=60 * 10)
def verify_mobile_otp(tmp_id: str, otp: str) -> None:
	try:
		if not tmp_id or not otp:
			frappe.throw(_("OTP and temporary ID are required"), frappe.ValidationError)

		login_manager = _authenticate_with_otp(otp, tmp_id)
		_validate_mobile_user_role()
		user_doc, access_token = _generate_user_token(login_manager)
		refresh_token = _create_refresh_token(
			user_doc, device_id=_get_device_id(), user_agent=_get_user_agent()
		)
		login_manager.logout()

		_clear_login_response()

		# Get mobile configuration
		mobile_config = _get_mobile_configuration_payload().get("configuration", [])

		frappe.local.response.update(
			_build_auth_response(
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


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(key="refresh_token", limit=get_mobile_login_ratelimit, seconds=60 * 60)
def refresh_token(refresh_token: str) -> dict[str, str]:
	"""Refresh access token using refresh token"""
	try:
		token_doc = _get_valid_refresh_token_doc(refresh_token)
		user_doc = frappe.get_doc("User", token_doc["user"])
		_validate_mobile_user_role_for_user(user_doc)
		_ensure_api_credentials(user_doc)
		access_token = _generate_auth_token(user_doc)
		new_refresh_token = _rotate_refresh_token(token_doc, user_doc)

		return _build_auth_response(
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
