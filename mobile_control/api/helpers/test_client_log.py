from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days
from frappe.utils import get_datetime
from frappe.utils import now_datetime
from frappe.tests import UnitTestCase

from mobile_control.api.helpers import client_log
from mobile_control.api.helpers.constants import REFRESH_TOKEN_TTL_DAYS

SAMPLE_INFO = {
	"app_name": "rf_mis_mobile",
	"app_version": "2.9.0",
	"build_number": "72",
	"platform": "android",
	"os_version": "13",
	"device_model": "Redmi Note 12",
	"device_id": "device-under-test",
	"user_agent": "Dart/3.5 (dart:io)",
}


class TestParseClientInfo(UnitTestCase):
	def test_parses_well_formed_client_info_header(self) -> None:
		header = (
			"app=rf_mis_mobile; ver=2.9.0+72; platform=android; "
			"os=13; model=Redmi Note 12; device=abc-123-uuid"
		)
		with patch("mobile_control.api.helpers.client_log.get_request_header", return_value=header):
			info = client_log.parse_client_info()

		self.assertEqual(info["app_name"], "rf_mis_mobile")
		self.assertEqual(info["app_version"], "2.9.0")
		self.assertEqual(info["build_number"], "72")
		self.assertEqual(info["platform"], "android")
		self.assertEqual(info["os_version"], "13")
		self.assertEqual(info["device_model"], "Redmi Note 12")
		self.assertEqual(info["device_id"], "abc-123-uuid")

	def test_truncates_values_to_the_data_field_limit(self) -> None:
		"""Values land in varchar(140) columns — an oversized value must not blow up the insert."""
		header = f"model={'x' * 500}; app=rf_mis_mobile"
		with patch("mobile_control.api.helpers.client_log.get_request_header", return_value=header):
			info = client_log.parse_client_info()

		self.assertEqual(len(info["device_model"]), 140)

	def test_ignores_malformed_header_segments(self) -> None:
		header = "garbage; ;=; ver=2.9.0+72; =orphan; unknown_key=x"
		with patch("mobile_control.api.helpers.client_log.get_request_header", return_value=header):
			info = client_log.parse_client_info()

		self.assertEqual(info["app_version"], "2.9.0")
		self.assertIsNone(info["device_model"])

	def test_returns_defaults_when_no_request_is_bound(self) -> None:
		"""Never raise at the caller — login must not fail because telemetry could not read a header."""
		info = client_log.parse_client_info()

		self.assertEqual(info, dict.fromkeys(client_log.CLIENT_INFO_FIELDS))

	def test_falls_back_to_request_metadata_when_header_missing(self) -> None:
		"""Older APKs send no X-Client-Info — keep the legacy device_id/User-Agent."""
		with (
			patch("mobile_control.api.helpers.client_log.get_request_header", return_value=None),
			patch(
				"mobile_control.api.helpers.client_log.get_request_metadata",
				return_value=("legacy-device-1", "Dart/3.5 (dart:io)"),
			),
		):
			info = client_log.parse_client_info()

		self.assertEqual(info["device_id"], "legacy-device-1")
		self.assertEqual(info["user_agent"], "Dart/3.5 (dart:io)")
		self.assertIsNone(info["app_version"])


class TestRecordClientEvent(IntegrationTestCase):
	def setUp(self) -> None:
		# The class shares one transaction, so each test must start from a clean device.
		frappe.db.delete("Mobile Login Event", {"user": "Administrator"})
		frappe.db.delete("Mobile Device Log", {"user": "Administrator"})

	def _record(self, event: str, info: dict | None = None) -> None:
		with patch(
			"mobile_control.api.helpers.client_log.parse_client_info",
			return_value=dict(info or SAMPLE_INFO),
		):
			client_log.record_client_event(event, user="Administrator")

	def _device_rows(self) -> list[dict]:
		return frappe.get_all(
			"Mobile Device Log",
			filters={"user": "Administrator", "device_id": "device-under-test"},
			fields=["name", "app_version", "build_number", "device_model", "login_count", "last_login"],
		)

	def test_login_creates_device_row_with_reported_app_version(self) -> None:
		self._record("Login")

		rows = self._device_rows()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["app_version"], "2.9.0")
		self.assertEqual(rows[0]["build_number"], "72")
		self.assertEqual(rows[0]["device_model"], "Redmi Note 12")
		self.assertEqual(rows[0]["login_count"], 1)
		self.assertIsNotNone(rows[0]["last_login"])

	def test_repeat_login_updates_the_same_row_and_counts_logins(self) -> None:
		self._record("Login")
		self._record("Login")

		rows = self._device_rows()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["login_count"], 2)

	def test_upgraded_app_version_replaces_the_stored_version(self) -> None:
		self._record("Login")
		self._record("Login", {**SAMPLE_INFO, "app_version": "3.0.0", "build_number": "80"})

		rows = self._device_rows()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["app_version"], "3.0.0")

	def test_each_event_appends_to_the_login_history(self) -> None:
		self._record("Login")
		self._record("Token Refresh")
		self._record("Logout")

		events = frappe.get_all(
			"Mobile Login Event",
			filters={"user": "Administrator", "device_id": "device-under-test"},
			fields=["event", "app_version"],
		)
		self.assertEqual(len(events), 3)
		self.assertEqual({e["event"] for e in events}, {"Login", "Token Refresh", "Logout"})
		self.assertEqual({e["app_version"] for e in events}, {"2.9.0"})

	def test_token_refresh_does_not_increment_login_count(self) -> None:
		self._record("Login")
		self._record("Token Refresh")

		self.assertEqual(self._device_rows()[0]["login_count"], 1)

	def test_swallows_write_failures_so_login_never_breaks(self) -> None:
		"""login() turns any exception into 'Unable to login' — telemetry must not be that exception."""
		with patch(
			"mobile_control.api.helpers.client_log._upsert_device_log",
			side_effect=Exception("db is on fire"),
		):
			result = client_log.record_client_event("Login", user="Administrator")

		self.assertIsNone(result)

	def test_login_marks_session_active_with_refresh_token_expiry(self) -> None:
		self._record("Login")

		row = frappe.db.get_value(
			"Mobile Device Log",
			{"user": "Administrator", "device_id": "device-under-test"},
			["session_active", "token_expires_at"],
			as_dict=True,
		)
		self.assertEqual(row["session_active"], 1)
		expected = add_days(now_datetime(), REFRESH_TOKEN_TTL_DAYS)
		self.assertLess(abs((row["token_expires_at"] - expected).total_seconds()), 120)

	def test_logout_clears_the_active_session(self) -> None:
		self._record("Login")
		self._record("Logout")

		row = frappe.db.get_value(
			"Mobile Device Log",
			{"user": "Administrator", "device_id": "device-under-test"},
			["session_active", "token_expires_at"],
			as_dict=True,
		)
		self.assertEqual(row["session_active"], 0)
		self.assertIsNone(row["token_expires_at"])

	def test_event_without_device_identity_reuses_the_last_seen_device(self) -> None:
		"""Logout carries no device_id — it must close the existing row, not create an empty one."""
		self._record("Login")
		self._record("Logout", {**SAMPLE_INFO, "device_id": None, "device_model": None})

		rows = frappe.get_all(
			"Mobile Device Log",
			filters={"user": "Administrator"},
			fields=["device_id", "device_model", "session_active"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["device_id"], "device-under-test")
		self.assertEqual(rows[0]["device_model"], "Redmi Note 12")
		self.assertEqual(rows[0]["session_active"], 0)

	def test_purge_removes_events_past_the_retention_window(self) -> None:
		self._record("Login")
		stale = frappe.get_all("Mobile Login Event", filters={"user": "Administrator"}, pluck="name")[0]
		frappe.db.set_value(
			"Mobile Login Event",
			stale,
			"event_time",
			add_days(now_datetime(), -(client_log.LOGIN_EVENT_RETENTION_DAYS + 1)),
			update_modified=False,
		)
		self._record("Token Refresh")

		client_log.purge_old_login_events()

		remaining = frappe.get_all(
			"Mobile Login Event", filters={"user": "Administrator"}, fields=["event"]
		)
		self.assertEqual([r["event"] for r in remaining], ["Token Refresh"])

	def test_login_captures_user_details_from_the_user_record(self) -> None:
		"""The list should read as a person, not just an email address."""
		self._record("Login")

		row = frappe.db.get_value(
			"Mobile Device Log",
			{"user": "Administrator", "device_id": "device-under-test"},
			["user_full_name", "user_enabled", "user_type", "account_last_login"],
			as_dict=True,
		)
		expected = frappe.db.get_value(
			"User", "Administrator", ["full_name", "enabled", "user_type", "last_login"], as_dict=True
		)
		self.assertEqual(row["user_full_name"], expected["full_name"])
		self.assertEqual(row["user_enabled"], expected["enabled"])
		self.assertEqual(row["user_type"], expected["user_type"])
		# User.last_login is a Data field on User but a Datetime column here — compare as datetimes.
		self.assertEqual(row["account_last_login"], get_datetime(expected["last_login"]))

	def test_user_details_refresh_on_a_later_event(self) -> None:
		"""Values are as-of-last-activity, so a rename must land on the next event."""
		self._record("Login")
		frappe.db.set_value("User", "Administrator", "full_name", "Renamed Admin", update_modified=False)

		self._record("Token Refresh")

		self.assertEqual(
			frappe.db.get_value(
				"Mobile Device Log",
				{"user": "Administrator", "device_id": "device-under-test"},
				"user_full_name",
			),
			"Renamed Admin",
		)


class TestTouchLastSeen(IntegrationTestCase):
	STALE = 3 * 24 * 3600

	def setUp(self) -> None:
		frappe.db.delete("Mobile Device Log", {"user": "Administrator"})
		frappe.cache.delete_value(client_log.last_seen_cache_key("Administrator"))
		frappe.local.flags.is_mobile_client = True

	def tearDown(self) -> None:
		frappe.local.flags.is_mobile_client = False
		frappe.cache.delete_value(client_log.last_seen_cache_key("Administrator"))

	def _seed_stale_device(self) -> str:
		doc = frappe.new_doc("Mobile Device Log")
		doc.user = "Administrator"
		doc.device_id = "device-under-test"
		doc.last_seen = add_days(now_datetime(), -3)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _age_seconds(self, name: str) -> float:
		return (now_datetime() - frappe.db.get_value("Mobile Device Log", name, "last_seen")).total_seconds()

	def test_refreshes_last_seen_for_a_mobile_client(self) -> None:
		name = self._seed_stale_device()

		client_log.touch_last_seen()

		self.assertLess(self._age_seconds(name), 120)

	def test_is_throttled_within_the_window(self) -> None:
		name = self._seed_stale_device()
		client_log.touch_last_seen()
		frappe.db.set_value(
			"Mobile Device Log", name, "last_seen", add_days(now_datetime(), -3), update_modified=False
		)

		client_log.touch_last_seen()

		self.assertGreater(self._age_seconds(name), 3600)

	def test_does_not_create_a_row_for_a_user_without_a_device(self) -> None:
		client_log.touch_last_seen()

		self.assertEqual(frappe.db.count("Mobile Device Log", {"user": "Administrator"}), 0)
