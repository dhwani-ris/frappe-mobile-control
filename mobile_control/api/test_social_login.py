from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

import frappe
from frappe.tests import UnitTestCase
from mobile_control.api import api_auth
from mobile_control.api.helpers import social_login


class TestSocialLogin(UnitTestCase):
	def test_provider_list_discovery(self) -> None:
		rows = [
			{
				"name": "Google",
				"provider_name": "Google",
				"enable_social_login": 1,
				"icon_url": "https://x/g.png",
			},
			{"name": "GitHub", "provider_name": "GitHub", "enable_social_login": 1},
		]
		with patch("mobile_control.api.helpers.social_login._get_social_login_key_rows", return_value=rows):
			result = api_auth.get_social_login_providers()

		assert result == {
			"providers": [
				{"id": "github", "label": "GitHub", "icon_url": None},
				{"id": "google", "label": "Google", "icon_url": "https://x/g.png"},
			]
		}

	def test_authorize_url_generation(self) -> None:
		row = {"name": "Google", "provider_name": "Google", "enable_social_login": 1}
		with (
			patch("mobile_control.api.helpers.social_login.get_provider_row", return_value=row),
			patch(
				"mobile_control.api.helpers.social_login.get_allowed_redirect_uris",
				return_value={"frappemobilesdk://oauth/callback"},
			),
			patch(
				"mobile_control.api.api_auth.get_oauth2_authorize_url",
				return_value="https://accounts.google.com/o/oauth2/v2/auth?client_id=social",
			) as oauth_social,
		):
			result = api_auth.get_social_authorize_url(
				provider="google",
				client_id="abc123",
				redirect_uri="frappemobilesdk://oauth/callback",
				state="state-1",
				code_challenge="a" * 43,
				code_challenge_method="S256",
			)

		parsed = urlparse(result["authorize_url"])
		query = parse_qs(parsed.query)
		assert parsed.scheme == "https"
		assert parsed.netloc == "accounts.google.com"
		assert query["client_id"] == ["social"]
		oauth_social.assert_called_once()
		called_provider, called_redirect = oauth_social.call_args.args
		assert called_provider == "Google"
		redirect_query = parse_qs(urlparse(called_redirect).query)
		assert redirect_query["client_id"] == ["abc123"]
		assert redirect_query["redirect_uri"] == ["frappemobilesdk://oauth/callback"]
		assert redirect_query["response_type"] == ["code"]
		assert redirect_query["scope"] == ["openid all"]
		assert redirect_query["state"] == ["state-1"]
		assert redirect_query["code_challenge"] == ["a" * 43]
		assert redirect_query["code_challenge_method"] == ["S256"]

	def test_invalid_provider(self) -> None:
		with (
			patch("mobile_control.api.helpers.social_login.get_provider_row", return_value=None),
			patch(
				"mobile_control.api.helpers.social_login.get_allowed_redirect_uris",
				return_value={"frappemobilesdk://oauth/callback"},
			),
		):
			with self.assertRaises(frappe.ValidationError):
				api_auth.get_social_authorize_url(
					provider="unknown",
					client_id="abc123",
					redirect_uri="frappemobilesdk://oauth/callback",
					state="state-1",
					code_challenge="challenge",
					code_challenge_method="S256",
				)

	def test_missing_params(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			api_auth.get_social_authorize_url(
				provider="google",
				client_id=None,
				redirect_uri="frappemobilesdk://oauth/callback",
				state="state-1",
				code_challenge="challenge",
				code_challenge_method="S256",
			)

	def test_disabled_provider(self) -> None:
		rows = [
			{"name": "Google", "provider_name": "Google", "enable_social_login": 0},
		]
		with patch("mobile_control.api.helpers.social_login._get_social_login_key_rows", return_value=rows):
			providers = social_login.discover_social_login_providers()
		assert providers == []

	def test_propagates_social_provider_validation_error(self) -> None:
		row = {"name": "Google", "provider_name": "Google", "enable_social_login": 1}
		with (
			patch("mobile_control.api.helpers.social_login.get_provider_row", return_value=row),
			patch(
				"mobile_control.api.helpers.social_login.get_allowed_redirect_uris",
				return_value={"frappemobilesdk://oauth/callback"},
			),
			patch(
				"mobile_control.api.api_auth.get_oauth2_authorize_url",
				side_effect=frappe.ValidationError,
			),
		):
			with self.assertRaises(frappe.ValidationError):
				api_auth.get_social_authorize_url(
					provider="google",
					client_id="abc123",
					redirect_uri="frappemobilesdk://oauth/callback",
					state="state-1",
					code_challenge="a" * 43,
					code_challenge_method="S256",
				)

	def test_rejects_invalid_code_challenge(self) -> None:
		row = {"name": "Google", "provider_name": "Google", "enable_social_login": 1}
		with (
			patch("mobile_control.api.helpers.social_login.get_provider_row", return_value=row),
			patch(
				"mobile_control.api.helpers.social_login.get_provider_authorize_endpoint",
				return_value="https://accounts.google.com/o/oauth2/v2/auth",
			),
			patch(
				"mobile_control.api.helpers.social_login.get_allowed_redirect_uris",
				return_value={"frappemobilesdk://oauth/callback"},
			),
		):
			with self.assertRaises(frappe.ValidationError):
				api_auth.get_social_authorize_url(
					provider="google",
					client_id="abc123",
					redirect_uri="frappemobilesdk://oauth/callback",
					state="state-1",
					code_challenge="bad!*",
					code_challenge_method="S256",
				)
