# Copyright (c) 2026, DHWANI RIS and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class MobileConfiguration(Document):
	def on_update(self) -> None:
		_ensure_mobile_uuid_fields(self)


def _ensure_mobile_uuid_fields(config: "MobileConfiguration") -> None:
	doctypes = {row.mobile_doctype for row in (config.table_lwis or []) if row.mobile_doctype}
	for doctype in doctypes:
		_ensure_mobile_uuid_field(doctype)


def _ensure_mobile_uuid_field(doctype: str) -> None:
	if not frappe.db.exists("DocType", doctype):
		return
	if frappe.get_meta(doctype, cached=True).has_field("mobile_uuid"):
		return

	existing = frappe.get_all(
		"Custom Field",
		filters={"dt": doctype, "fieldname": "mobile_uuid"},
		pluck="name",
		limit=1,
	)
	if existing:
		frappe.db.set_value(
			"Custom Field",
			existing[0],
			{"label": "Mobile UUID", "fieldtype": "Data", "read_only": 1},
			update_modified=False,
		)
		return

	custom_field = frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": doctype,
			"fieldname": "mobile_uuid",
			"label": "Mobile UUID",
			"fieldtype": "Data",
			"read_only": 1,
			"insert_after": "name",
		}
	)
	custom_field.insert(ignore_permissions=True)


def update_doctype_meta_modified(doc: Document, method: str | None = None) -> None:
	doctype_name = _get_doctype_name_from_doc(doc)
	if not doctype_name:
		return

	rows = frappe.get_all(
		"Mobile Configuration Form",
		filters={
			"parenttype": "Mobile Configuration",
			"parentfield": "table_lwis",
			"mobile_doctype": doctype_name,
		},
		pluck="name",
	)
	if not rows:
		return

	modified_at = doc.modified or now_datetime()
	for row_name in rows:
		frappe.db.set_value(
			"Mobile Configuration Form",
			row_name,
			"doctype_meta_modifed_at",
			modified_at,
			update_modified=False,
		)


def _get_doctype_name_from_doc(doc: Document) -> str | None:
	if doc.doctype == "DocType":
		return doc.name
	if doc.doctype == "Custom Field":
		return doc.dt
	if doc.doctype == "Property Setter":
		return doc.doc_type
	return None
