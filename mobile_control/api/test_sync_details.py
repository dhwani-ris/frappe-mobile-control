from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date
from mobile_control.api.sync_details import get_sync_details


def _probe(doctype: str, since: str) -> dict:
	return get_sync_details([{"doctype": doctype, "since": since}])["doctypes"][0]


class TestSyncDetailsChangeProbe(IntegrationTestCase):
	"""The per-doctype "anything modified since the watermark?" probe."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.todo = frappe.get_doc({"doctype": "ToDo", "description": "sync_details probe"}).insert()

	def test_probe_query_is_not_ordered(self) -> None:
		# Catches the probe inheriting get_list's default `ORDER BY creation DESC`.
		# With the LIMIT, MariaDB walks the `creation` index over the whole table and
		# checks every row against the user's User Permission conditions, which is very
		# slow on large tables when the user matches few or no rows.
		queries: list[str] = []
		orig_sql = frappe.db.__class__.sql

		def _record(db, *args, **kwargs):
			ret = orig_sql(db, *args, **kwargs)
			queries.append(str(db.last_query))
			return ret

		frappe.db.__class__.sql = _record
		try:
			_probe("ToDo", "2000-01-01 00:00:00")
		finally:
			frappe.db.__class__.sql = orig_sql

		probe_queries = [q for q in queries if "from `tabtodo`" in q.lower()]
		self.assertEqual(len(probe_queries), 1, queries)
		self.assertNotIn("order by", probe_queries[0].lower())

	def test_changed_and_count_follow_since(self) -> None:
		# Catches the probe ignoring `since` (always "changed") or reporting a stale count.
		before = str(add_to_date(self.todo.modified, seconds=-1))
		after = str(add_to_date(self.todo.modified, seconds=1))

		changed = _probe("ToDo", before)
		unchanged = _probe("ToDo", after)

		self.assertTrue(changed["changed"])
		self.assertGreaterEqual(changed["count"], 1)
		self.assertEqual((unchanged["changed"], unchanged["count"]), (False, 0))
