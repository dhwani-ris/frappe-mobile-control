"""Helpers for social login provider discovery and authorize URL generation."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

import frappe
from frappe import _

SOCIAL_LOGIN_KEY_DOCTYPE = "Social Login Key"
DEFAULT_SCOPE = "openid all"
DEFAULT_REDIRECT_URIS = {"frappemobilesdk://oauth/callback"}

# Well-known provider authorization endpoints used when not configured in DB.
PROVIDER_AUTHORIZE_ENDPOINTS = {
	"google": "https://accounts.google.com/o/oauth2/v2/auth",
	"microsoft": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
	"github": "https://github.com/login/oauth/authorize",
	"facebook": "https://www.facebook.com/v19.0/dialog/oauth",
	"gitlab": "https://gitlab.com/oauth/authorize",
	"apple": "https://appleid.apple.com/auth/authorize",
}


def normalize_provider_id(value: str | None) -> str:
	"""Normalize provider IDs for consistent matching."""
	text = (value or "").strip().lower()
	if not text:
		return ""
	text = re.sub(r"[\s_]+", "-", text)
	text = re.sub(r"[^a-z0-9-]", "", text)
	return text.replace("-", "")


def get_allowed_redirect_uris() -> set[str]:
	"""Return allowed redirect URIs with site-config overrides."""
	allowed = set(DEFAULT_REDIRECT_URIS)
	for config_key in ("mobile_auth_redirect_uris", "mobile_control_redirect_uris"):
		values = frappe.conf.get(config_key)
		for value in _flatten_redirect_values(values):
			allowed.add(value)
	return {u.strip() for u in allowed if u and str(u).strip()}


def validate_redirect_uri(redirect_uri: str) -> None:
	"""Validate redirect URI against allowlisted values."""
	if redirect_uri not in get_allowed_redirect_uris():
		frappe.throw(
			_("Invalid redirect_uri. Allowed values: {0}").format(
				", ".join(sorted(get_allowed_redirect_uris()))
			),
			frappe.ValidationError,
		)


def discover_social_login_providers() -> list[dict[str, str | None]]:
	"""Discover enabled social login providers from Social Login Key."""
	if not frappe.db.exists("DocType", SOCIAL_LOGIN_KEY_DOCTYPE):
		return []

	rows = _get_social_login_key_rows()
	providers = _extract_social_providers(rows)
	providers.sort(key=lambda item: (item.get("label") or item["id"]).lower())
	return providers


def get_provider_row(provider: str) -> dict | None:
	"""Return enabled provider row matching provider id."""
	target = normalize_provider_id(provider)
	if not target:
		return None
	for row in _get_social_login_key_rows():
		if not _is_enabled_row(row):
			continue
		row_provider_id = normalize_provider_id(
			_first_present_value(row, ("provider_name", "provider", "name"))
		)
		if row_provider_id == target:
			return row
	return None


def get_provider_authorize_endpoint(provider_row: dict, provider_id: str) -> str:
	"""Resolve authorize endpoint from DB fields or known provider map."""
	for fieldname in ("authorize_url", "authorization_url", "auth_url"):
		value = (provider_row.get(fieldname) or "").strip()
		if value:
			return value

	base_url = (provider_row.get("base_url") or "").strip()
	if base_url:
		if provider_id in PROVIDER_AUTHORIZE_ENDPOINTS:
			default_path = urlparse(PROVIDER_AUTHORIZE_ENDPOINTS[provider_id]).path
			base_parts = urlparse(base_url)
			if base_parts.path:
				return base_url
			return urlunparse(
				(
					base_parts.scheme or "https",
					base_parts.netloc or base_parts.path,
					default_path,
					"",
					"",
					"",
				)
			)
		return base_url

	default_endpoint = PROVIDER_AUTHORIZE_ENDPOINTS.get(provider_id)
	if default_endpoint:
		return default_endpoint

	frappe.throw(
		_(
			"Unable to resolve authorize URL for provider '{0}'. Configure authorize_url on Social Login Key."
		).format(provider_id),
		frappe.ValidationError,
	)
	return ""


def build_authorize_url(authorize_endpoint: str, params: dict[str, str]) -> str:
	"""Append OAuth params to provider endpoint while preserving existing query."""
	validate_authorize_endpoint(authorize_endpoint)
	parsed = urlparse(authorize_endpoint)
	existing_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
	existing_query.update(params)
	return urlunparse(parsed._replace(query=urlencode(existing_query)))


def validate_authorize_endpoint(authorize_endpoint: str) -> None:
	"""Reject unsafe or malformed authorize endpoints."""
	parsed = urlparse((authorize_endpoint or "").strip())
	if not parsed.scheme or not parsed.netloc:
		frappe.throw(_("Invalid provider authorize endpoint URL"), frappe.ValidationError)

	if parsed.scheme.lower() != "https":
		frappe.throw(_("Provider authorize endpoint must use HTTPS"), frappe.ValidationError)

	hostname = (parsed.hostname or "").strip().lower()
	if not hostname:
		frappe.throw(_("Invalid provider authorize endpoint host"), frappe.ValidationError)

	if hostname in {"localhost"} or hostname.endswith(".local"):
		frappe.throw(_("Provider authorize endpoint host is not allowed"), frappe.ValidationError)

	try:
		ip = ipaddress.ip_address(hostname)
	except ValueError:
		return

	if (
		ip.is_private
		or ip.is_loopback
		or ip.is_link_local
		or ip.is_multicast
		or ip.is_reserved
		or ip.is_unspecified
	):
		frappe.throw(_("Provider authorize endpoint IP is not allowed"), frappe.ValidationError)


def _get_social_login_key_rows() -> list[dict]:
	meta = frappe.get_meta(SOCIAL_LOGIN_KEY_DOCTYPE)
	available = {df.fieldname for df in meta.fields}
	query_fields = ["name"]
	for fieldname in (
		"provider_name",
		"provider",
		"enabled",
		"enable_social_login",
		"icon",
		"icon_url",
		"image",
		"logo",
		"authorize_url",
		"authorization_url",
		"auth_url",
		"base_url",
	):
		if fieldname in available:
			query_fields.append(fieldname)
	return frappe.get_all(SOCIAL_LOGIN_KEY_DOCTYPE, fields=query_fields, limit_page_length=0)


def _extract_social_providers(rows: list[dict]) -> list[dict[str, str | None]]:
	seen: set[str] = set()
	providers: list[dict[str, str | None]] = []
	for row in rows:
		if not _is_enabled_row(row):
			continue

		provider_id = normalize_provider_id(_first_present_value(row, ("provider_name", "provider", "name")))
		if not provider_id or provider_id in seen:
			continue
		seen.add(provider_id)

		label = _first_present_value(row, ("provider_name", "provider", "name")) or provider_id.title()
		icon_url = _first_present_value(row, ("icon_url", "icon", "image", "logo"))
		providers.append({"id": provider_id, "label": label, "icon_url": icon_url or None})
	return providers


def _is_enabled_row(row: dict) -> bool:
	if "enable_social_login" in row:
		return bool(row.get("enable_social_login"))
	if "enabled" in row:
		return bool(row.get("enabled"))
	return True


def _first_present_value(row: dict, fieldnames: Iterable[str]) -> str:
	for fieldname in fieldnames:
		value = row.get(fieldname)
		if value is None:
			continue
		text = str(value).strip()
		if text:
			return text
	return ""


def _flatten_redirect_values(values: object) -> list[str]:
	if not values:
		return []
	if isinstance(values, str):
		return [item.strip() for item in values.split(",") if item.strip()]
	if isinstance(values, list | tuple | set):
		items: list[str] = []
		for item in values:
			if item is None:
				continue
			text = str(item).strip()
			if text:
				items.append(text)
		return items
	return []
