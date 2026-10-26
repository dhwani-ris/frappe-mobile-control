from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from mobile_control.api import bulk_fetch

try:
	from frappe.tests import IntegrationTestCase
except ImportError:  # Frappe v15
	from frappe.tests.utils import FrappeTestCase as IntegrationTestCase

PARENT = "MC Bulk Fetch Test"
CHILD = "MC Bulk Fetch Test Row"
ROLE = "MC Bulk Fetch Reader"
USER = "mc.bulk.reader@example.com"
HAS_MASKING = hasattr(Document, "mask_fields")  # v16+


def drop_note(doctype, rows):
	for row in rows:
		row.pop("note", None)
	return rows


class TestBulkFetchFieldPermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_make_role_and_user()
		_make_doctypes()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_reader_does_not_get_higher_permlevel_fields(self):
		name = _make_doc()
		frappe.set_user(USER)
		doc = bulk_fetch.get_docs_with_children(PARENT, [name])[0]
		self.assertEqual(doc["title"], "Farmer 1")
		self.assertIsNone(doc.get("secret_note"))
		self.assertIsNone(doc["rows"][0].get("account_no"))

	@unittest.skipUnless(HAS_MASKING, "field masking needs Frappe v16")
	def test_reader_gets_masked_value(self):
		name = _make_doc()
		frappe.set_user(USER)
		doc = bulk_fetch.get_docs_with_children(PARENT, [name])[0]
		self.assertNotEqual(doc["mobile"], "9876543210")
		self.assertIn("X", doc["mobile"])

	def test_administrator_gets_every_field(self):
		name = _make_doc()
		doc = bulk_fetch.get_docs_with_children(PARENT, [name])[0]
		self.assertEqual(doc["secret_note"], "hidden")
		self.assertEqual(doc["mobile"], "9876543210")
		self.assertEqual(doc["rows"][0]["account_no"], "123456789012")

	def test_row_filter_hook_runs_once_per_batch(self):
		names = [_make_doc(), _make_doc()]
		get_hooks = frappe.get_hooks
		filter_path = f"{__name__}.drop_note"

		def hooks(hook=None, *args, **kwargs):
			if hook == bulk_fetch.ROW_FILTERS_HOOK:
				return [filter_path]
			return get_hooks(hook, *args, **kwargs)

		with (
			patch.object(frappe, "get_hooks", side_effect=hooks),
			patch(f"{__name__}.drop_note", wraps=drop_note) as spy,
		):
			docs = bulk_fetch.get_docs_with_children(PARENT, names)

		spy.assert_called_once()
		self.assertEqual(len(docs), 2)
		self.assertTrue(all("note" not in doc for doc in docs))


def _make_role_and_user():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert()
	if not frappe.db.exists("User", USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": USER,
				"first_name": "MC Reader",
				"send_welcome_email": 0,
				"roles": [{"role": ROLE}],
			}
		).insert()


def _make_doctypes():
	# DocType DDL commits implicitly, so these persist across runs; create only once
	if frappe.db.exists("DocType", PARENT):
		return

	if not frappe.db.exists("DocType", CHILD):
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": CHILD,
				"module": "Mobile Control",
				"custom": 1,
				"istable": 1,
				"fields": [
					{"fieldname": "bank", "fieldtype": "Data", "label": "Bank"},
					{"fieldname": "account_no", "fieldtype": "Data", "label": "Account No", "permlevel": 1},
				],
			}
		).insert()

	mobile = {"fieldname": "mobile", "fieldtype": "Data", "label": "Mobile"}
	if HAS_MASKING:
		mobile["mask"] = 1
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": PARENT,
			"module": "Mobile Control",
			"custom": 1,
			"autoname": "hash",
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{"fieldname": "note", "fieldtype": "Data", "label": "Note"},
				mobile,
				{"fieldname": "secret_note", "fieldtype": "Data", "label": "Secret Note", "permlevel": 1},
				{"fieldname": "rows", "fieldtype": "Table", "label": "Rows", "options": CHILD},
			],
			"permissions": [
				{"role": "System Manager", "read": 1, "write": 1, "create": 1},
				{"role": "System Manager", "read": 1, "write": 1, "permlevel": 1},
				{"role": ROLE, "read": 1},
			],
		}
	).insert()


def _make_doc():
	return (
		frappe.get_doc(
			{
				"doctype": PARENT,
				"title": "Farmer 1",
				"note": "visible",
				"mobile": "9876543210",
				"secret_note": "hidden",
				"rows": [{"bank": "SBI", "account_no": "123456789012"}],
			}
		)
		.insert()
		.name
	)
