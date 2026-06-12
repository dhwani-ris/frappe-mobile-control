from __future__ import annotations

import frappe
from frappe.tests import UnitTestCase
from frappe.utils import add_to_date
from frappe.utils import now_datetime
from mobile_control import tasks as mc_tasks
from mobile_control.api import error_log


def _payload(signature="sig-1", count=1, examples=None):
	return {
		"signature": signature,
		"doctype_name": "Household Survey",
		"operation": "INSERT",
		"http_status": 417,
		"exc_type": "ValidationError",
		"request_method": "POST",
		"request_url": "https://prod.example.com/api/resource/Household Survey",
		"error_user": "mobileuser@example.com",
		"error_user_roles": ["Mobile User"],
		"trace_id": "",
		"occurrence_count": count,
		"last_seen_millis": 1000,
		"examples": examples
		if examples is not None
		else [
			{
				"mobile_uuid": "uuid-a",
				"request_payload": '{"doctype":"Household Survey","mobile_uuid":"uuid-a"}',
				"response_body": '{"exc_type":"ValidationError"}',
				"occurred_at_millis": 1000,
			}
		],
	}


class TestReportError(UnitTestCase):
	def tearDown(self):
		frappe.db.delete("Mobile Error Log", {"signature": ("like", "sig-%")})
		frappe.db.commit()

	def test_first_post_creates_row_and_renders_curl(self):
		error_log.report_error(payload=_payload())
		row = frappe.get_doc("Mobile Error Log", {"signature": "sig-1"})
		self.assertEqual(row.occurrence_count, 1)
		self.assertEqual(row.doctype_name, "Household Survey")
		self.assertEqual(len(row.examples), 1)
		curl = row.examples[0].curl_command
		self.assertIn("{{TOKEN}}", curl)
		self.assertIn("{{HOST}}", curl)
		self.assertIn("/api/resource/Household Survey", curl)
		self.assertNotIn("prod.example.com", curl)  # host swapped out

	def test_second_post_same_signature_upserts_not_duplicates(self):
		error_log.report_error(payload=_payload(count=2))
		error_log.report_error(
			payload=_payload(
				count=3,
				examples=[
					{
						"mobile_uuid": "uuid-b",
						"request_payload": "{}",
						"response_body": "{}",
						"occurred_at_millis": 2000,
					}
				],
			)
		)
		rows = frappe.get_all("Mobile Error Log", filters={"signature": "sig-1"})
		self.assertEqual(len(rows), 1)
		row = frappe.get_doc("Mobile Error Log", rows[0].name)
		self.assertEqual(row.occurrence_count, 5)  # 2 + 3 cumulative

	def test_examples_evict_to_last_5(self):
		for i in range(7):
			error_log.report_error(
				payload=_payload(
					count=1,
					examples=[
						{
							"mobile_uuid": f"uuid-{i}",
							"request_payload": "{}",
							"response_body": "{}",
							"occurred_at_millis": 1000 + i,
						}
					],
				)
			)
		row = frappe.get_doc("Mobile Error Log", {"signature": "sig-1"})
		self.assertEqual(len(row.examples), 5)
		uuids = [e.mobile_uuid for e in row.examples]
		self.assertEqual(uuids, ["uuid-2", "uuid-3", "uuid-4", "uuid-5", "uuid-6"])

	def test_ignore_links_allows_unknown_user(self):
		p = _payload(signature="sig-ghost")
		p["error_user"] = "deactivated-ghost@example.com"
		error_log.report_error(payload=p)  # must not raise LinkValidationError
		row = frappe.get_doc("Mobile Error Log", {"signature": "sig-ghost"})
		self.assertEqual(row.error_user, "deactivated-ghost@example.com")
		frappe.db.delete("Mobile Error Log", {"signature": "sig-ghost"})

	def test_render_curl_swaps_host_and_token(self):
		curl = error_log.render_curl(
			"POST",
			"https://prod.example.com/api/resource/Foo?x=1",
			'{"a":1}',
		)
		self.assertIn("curl -X POST", curl)
		self.assertIn("{{HOST}}/api/resource/Foo?x=1", curl)
		self.assertIn("Authorization: Bearer {{TOKEN}}", curl)
		self.assertIn("Content-Type: application/json", curl)
		self.assertNotIn("prod.example.com", curl)


class TestPurgeMobileErrorLogs(UnitTestCase):
	def tearDown(self):
		frappe.db.delete("Mobile Error Log", {"signature": ("like", "purge-%")})
		frappe.db.commit()

	def _make(self, signature, age_days):
		error_log.report_error(
			payload={
				"signature": signature,
				"doctype_name": "X",
				"operation": "INSERT",
				"http_status": 417,
				"exc_type": "ValidationError",
				"request_method": "POST",
				"request_url": "https://p/api/resource/X",
				"error_user": "u@x",
				"error_user_roles": [],
				"occurrence_count": 1,
				"examples": [],
			}
		)
		old = add_to_date(now_datetime(), days=-age_days)
		frappe.db.set_value(
			"Mobile Error Log",
			{"signature": signature},
			{"last_seen": old, "creation": old},
			update_modified=False,
		)
		frappe.db.commit()

	def test_purge_deletes_old_keeps_new(self):
		frappe.db.set_single_value("Mobile Configuration", "mobile_error_log_retention_days", 30)
		self._make("purge-old", age_days=45)
		self._make("purge-new", age_days=5)
		mc_tasks.purge_mobile_error_logs()
		frappe.db.commit()
		self.assertFalse(frappe.db.exists("Mobile Error Log", {"signature": "purge-old"}))
		self.assertTrue(frappe.db.exists("Mobile Error Log", {"signature": "purge-new"}))

	def test_zero_retention_disables_purge(self):
		frappe.db.set_single_value("Mobile Configuration", "mobile_error_log_retention_days", 0)
		self._make("purge-keep", age_days=999)
		mc_tasks.purge_mobile_error_logs()
		frappe.db.commit()
		self.assertTrue(frappe.db.exists("Mobile Error Log", {"signature": "purge-keep"}))
