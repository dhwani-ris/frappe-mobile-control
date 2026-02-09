# mobile_control/api/jwt_auth.py

import ast
import time
from datetime import datetime
from datetime import timedelta

import frappe
from cryptography.fernet import Fernet
from frappe import _


def get_secret() -> str:
	"""Fetch encryption secret from site config or generate a fallback."""
	return frappe.conf.get("encryption_key") or frappe.generate_hash(length=32)


def _create_encryption_payload(api_key: str, api_secret: str, expires_in: int) -> dict[str, any]:
	"""Create payload for encryption"""
	expires_at = int(time.time()) + expires_in
	return {"api_key": api_key, "api_secret": api_secret, "expires_at": expires_at}


def _encrypt_payload(payload: dict[str, any]) -> str:
	"""Encrypt payload using Fernet"""
	cipher_suite = Fernet(get_secret())
	encrypted_payload = cipher_suite.encrypt(str(payload).encode())
	return encrypted_payload.decode()


def encode_api_credentials(api_key: str, api_secret: str, expires_in: int = 2592000) -> str:
	"""
	Encrypt API credentials using Fernet encryption.
	Args:
	    api_key (str): The API key
	    api_secret (str): The API secret
	    expires_in (int): Token expiration time in seconds (default: 30 days)
	Returns:
	    str: Encrypted token
	"""
	try:
		payload = _create_encryption_payload(api_key, api_secret, expires_in)
		return _encrypt_payload(payload)
	except Exception:
		raise frappe.AuthenticationError(_("Failed to encode API credentials"))


def _decrypt_token_payload(encrypted_token: str) -> dict[str, any]:
	"""Decrypt token and return payload"""
	cipher_suite = Fernet(get_secret())
	decrypted_payload = cipher_suite.decrypt(encrypted_token.encode())
	return ast.literal_eval(decrypted_payload.decode())


def _validate_token_expiration(payload: dict[str, any]) -> None:
	"""Validate token expiration"""
	current_time = int(time.time())
	expires_at = payload.get("expires_at")

	if not expires_at:
		frappe.log_error("Token missing expiration timestamp")
		raise frappe.AuthenticationError(_("Invalid token format"))

	if current_time > expires_at:
		frappe.log_error(f"Token expired at {datetime.fromtimestamp(expires_at)}")
		raise frappe.AuthenticationError(_("Token has expired"))


def _extract_credentials(payload: dict[str, any]) -> tuple[str, str]:
	"""Extract and validate API credentials from payload"""
	api_key = payload.get("api_key")
	api_secret = payload.get("api_secret")

	if not api_key or not api_secret:
		raise frappe.AuthenticationError(_("Invalid token payload"))

	return api_key, api_secret


def decode_api_credentials(encrypted_token: str) -> tuple[str, str]:
	"""
	Decrypt API credentials and check expiration.
	Returns (api_key, api_secret) if valid, else raises AuthenticationError.
	"""
	try:
		payload = _decrypt_token_payload(encrypted_token)
		_validate_token_expiration(payload)
		return _extract_credentials(payload)
	except Exception:
		raise frappe.AuthenticationError(_("Invalid authentication token"))


def _extract_bearer_token() -> str | None:
	"""Extract Bearer token from Authorization header"""
	auth_header = frappe.get_request_header("Authorization")
	if not auth_header or not auth_header.startswith("Bearer "):
		return None
	return auth_header.split(" ", 1)[1].strip()


def _convert_to_frappe_auth(api_key: str, api_secret: str) -> None:
	"""Convert API credentials to Frappe's token format"""
	new_headers = dict(frappe.request.headers)
	new_headers["Authorization"] = f"token {api_key}:{api_secret}"
	frappe.request.headers = new_headers


def token_auth_middleware() -> None:
	"""
	Middleware to convert encrypted token to Frappe's default auth format.
	"""
	try:
		encrypted_token = _extract_bearer_token()
		if not encrypted_token:
			return  # No token, let Frappe handle as usual

		api_key, api_secret = decode_api_credentials(encrypted_token)
		_convert_to_frappe_auth(api_key, api_secret)
	except frappe.AuthenticationError as e:
		frappe.clear_messages()
		frappe.throw(str(e), frappe.AuthenticationError)
	except Exception:
		frappe.throw(_("Authentication failed"), frappe.AuthenticationError)
