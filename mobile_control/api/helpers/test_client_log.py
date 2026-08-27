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

	def test_caps_legacy_values_too_not_just_header_values(self) -> None:
		"""A long User-Agent would blow the varchar(140) insert and drop the user from the log."""
		with (
			patch("mobile_control.api.helpers.client_log.get_request_header", return_value=None),
			patch(
				"mobile_control.api.helpers.client_log.get_request_metadata",
				return_value=("d" * 300, "u" * 300),
			),
		):
			info = client_log.parse_client_info()

		self.assertEqual(len(info["device_id"]), 140)
		self.assertEqual(len(info["user_agent"]), 140)

	def test_coerces_a_non_string_device_id_to_text(self) -> None:
		"""form_dict values come from the request body and need not be strings."""
		with (
			patch("mobile_control.api.helpers.client_log.get_request_header", return_value=None),
			patch(
				"mobile_control.api.helpers.client_log.get_request_metadata",
				return_value=(["like", "%"], None),
			),
		):
			info = client_log.parse_client_info()

		self.assertIsInstance(info["device_id"], str)

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

	def test_survives_a_failure_inside_its_own_error_logging(self) -> None:
		"""log_error inserts a document; if that insert also fails, login must still succeed."""
		with (
			patch(
				"mobile_control.api.helpers.client_log._upsert_device_log",
				side_effect=Exception("db is on fire"),
			),
			patch("frappe.log_error", side_effect=Exception("error log is on fire too")),
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

	def test_blank_account_timestamps_do_not_break_the_write(self) -> None:
		"""User.last_login is a varchar on User but a Datetime column here."""
		original = frappe.db.get_value("User", "Administrator", "last_login")
		self.addCleanup(
			frappe.db.set_value, "User", "Administrator", "last_login", original, update_modified=False
		)
		frappe.db.set_value("User", "Administrator", "last_login", "", update_modified=False)

		self._record("Login")

		self.assertIsNone(
			frappe.db.get_value(
				"Mobile Device Log",
				{"user": "Administrator", "device_id": "device-under-test"},
				"account_last_login",
			)
		)

	def test_a_missing_user_row_does_not_wipe_captured_details(self) -> None:
		self._record("Login")
		with patch("frappe.db.get_value", return_value=None):
			snapshot = client_log._user_snapshot("ghost@example.com")

		self.assertEqual(snapshot, {})

	def test_does_not_guess_a_device_when_the_user_has_several(self) -> None:
		"""A legacy logout must not close the session on a phone it did not come from."""
		self._record("Login")
		self._record("Login", {**SAMPLE_INFO, "device_id": "second-device", "device_model": "Other Phone"})

		self._record("Logout", {**SAMPLE_INFO, "device_id": None, "device_model": None})

		rows = frappe.get_all(
			"Mobile Device Log",
			filters={"user": "Administrator"},
			fields=["device_id", "session_active"],
		)
		self.assertEqual(len(rows), 2, "no third row may be invented")
		self.assertEqual(
			{r["session_active"] for r in rows}, {1}, "neither device may be closed on a guess"
		)
		# The event itself is still recorded, just not attributed to a device.
		logouts = frappe.get_all(
			"Mobile Login Event", filters={"user": "Administrator", "event": "Logout"}, fields=["device_log"]
		)
		self.assertEqual(len(logouts), 1)
		self.assertIsNone(logouts[0]["device_log"])

	def test_a_racing_insert_does_not_produce_a_duplicate_row(self) -> None:
		"""Two simultaneous logins both see no row; the loser must update, not insert again."""
		self._record("Login")

		# Simulate the race: the lookup misses even though the row already exists.
		with patch("mobile_control.api.helpers.client_log._find_device_log", return_value=None):
			self._record("Login")

		rows = frappe.get_all(
			"Mobile Device Log",
			filters={"user": "Administrator", "device_id": "device-under-test"},
			fields=["name", "login_count"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["login_count"], 2)

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
		original = frappe.db.get_value("User", "Administrator", "full_name")
		self.addCleanup(
			frappe.db.set_value, "User", "Administrator", "full_name", original, update_modified=False
		)
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
		for device in (None, "device-under-test", "second-device"):
			frappe.cache.delete_value(client_log.last_seen_cache_key("Administrator", device))

	def tearDown(self) -> None:
		frappe.local.flags.is_mobile_client = False
		for device in (None, "device-under-test", "second-device"):
			frappe.cache.delete_value(client_log.last_seen_cache_key("Administrator", device))

	def _seed_stale_device(self, device_id: str = "device-under-test") -> str:
		doc = frappe.new_doc("Mobile Device Log")
		doc.user = "Administrator"
		doc.device_id = device_id
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


	def test_throttle_is_per_device_not_per_user(self) -> None:
		"""Two phones must each get their own last_seen refresh."""
		first = self._seed_stale_device()
		second = self._seed_stale_device(device_id="second-device")

		for device in ("device-under-test", "second-device"):
			with patch(
				"mobile_control.api.helpers.client_log.parse_client_info",
				return_value={**SAMPLE_INFO, "device_id": device},
			):
				client_log.touch_last_seen()

		self.assertLess(self._age_seconds(first), 120)
		self.assertLess(self._age_seconds(second), 120)

	def test_hook_ignores_requests_that_are_not_from_the_mobile_app(self) -> None:
		name = self._seed_stale_device()
		frappe.local.flags.is_mobile_client = False

		with patch("frappe.db.commit") as commit:
			client_log.touch_last_seen_after_request()

		commit.assert_not_called()
		self.assertGreater(self._age_seconds(name), 3600)

	def test_hook_commits_its_own_write(self) -> None:
		"""Frappe commits before after_request runs, so the hook must commit itself."""
		self._seed_stale_device()
		frappe.local.flags.is_mobile_client = True

		with (
			patch(
				"mobile_control.api.helpers.client_log.parse_client_info",
				return_value={**SAMPLE_INFO, "device_id": "device-under-test"},
			),
			patch("frappe.db.commit") as commit,
		):
			client_log.touch_last_seen_after_request()

		commit.assert_called_once()

	def test_hook_swallows_failures(self) -> None:
		frappe.local.flags.is_mobile_client = True
		with patch(
			"mobile_control.api.helpers.client_log.touch_last_seen",
			side_effect=Exception("boom"),
		):
			client_log.touch_last_seen_after_request()
