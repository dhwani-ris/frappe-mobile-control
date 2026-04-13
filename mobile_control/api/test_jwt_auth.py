from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase
from mobile_control.api import jwt_auth


class TestJwtAuthMiddleware(UnitTestCase):
	def test_mobile_control_bearer_token_is_decoded_and_converted(self) -> None:
		with (
			patch("mobile_control.api.jwt_auth._extract_bearer_token", return_value="gAAAA-mobile-token"),
			patch(
				"mobile_control.api.jwt_auth.decode_api_credentials", return_value=("k1", "s1")
			) as decode_mock,
			patch("mobile_control.api.jwt_auth._convert_to_frappe_auth") as convert_mock,
		):
			jwt_auth.token_auth_middleware()

		decode_mock.assert_called_once_with("gAAAA-mobile-token")
		convert_mock.assert_called_once_with("k1", "s1")

	def test_oauth_bearer_token_is_passed_through(self) -> None:
		with (
			patch("mobile_control.api.jwt_auth._extract_bearer_token", return_value="ya29.oauth-token"),
			patch("mobile_control.api.jwt_auth.decode_api_credentials") as decode_mock,
			patch("mobile_control.api.jwt_auth._convert_to_frappe_auth") as convert_mock,
		):
			jwt_auth.token_auth_middleware()

		decode_mock.assert_not_called()
		convert_mock.assert_not_called()

	def test_invalid_mobile_control_token_raises_authentication_error(self) -> None:
		with (
			patch("mobile_control.api.jwt_auth._extract_bearer_token", return_value="gAAAA-invalid-token"),
			patch(
				"mobile_control.api.jwt_auth.decode_api_credentials",
				side_effect=frappe.AuthenticationError("Invalid authentication token"),
			),
			patch("mobile_control.api.jwt_auth.frappe.clear_messages") as clear_mock,
		):
			with self.assertRaises(frappe.AuthenticationError):
				jwt_auth.token_auth_middleware()

		clear_mock.assert_called_once()
