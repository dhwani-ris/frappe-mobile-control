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
	# Cover both the configured top-level workspace doctypes and every
	# child doctype reachable through their Table / Table MultiSelect
	# fields, so the mobile SDK can round-trip child-row identity.
	top_level = {row.mobile_workspace_item for row in (config.table_lwis or []) if row.mobile_workspace_item}
	for doctype in top_level | _collect_child_doctypes(top_level):
		_ensure_mobile_uuid_field(doctype)


def _collect_child_doctypes(parent_doctypes: set[str]) -> set[str]:
	"""Child doctype names referenced by any parent's Table / Table
	MultiSelect fields. Read-only."""
	children: set[str] = set()
	for parent in parent_doctypes:
		if not frappe.db.exists("DocType", parent):
			continue
		meta = frappe.get_meta(parent, cached=True)
		for field in meta.get_table_fields():
			if field.options:
				children.add(field.options)
	return children


_MOBILE_CUSTOM_FIELDS = [
	{
		"fieldname": "mobile_uuid",
		"label": "Mobile UUID",
		"fieldtype": "Data",
		"read_only": 1,
		"hidden": 1,
		"unique": 1,
		"insert_after": "name",
	},
	{
		"fieldname": "mobile_created_at",
		"label": "Mobile Created At",
		"fieldtype": "Datetime",
		"read_only": 1,
		"hidden": 1,
		"unique": 0,
		"insert_after": "mobile_uuid",
	},
	{
		"fieldname": "mobile_latitude_longitude",
		"label": "Mobile Latitude Longitude",
		"fieldtype": "Geolocation",
		"read_only": 1,
		"hidden": 1,
		"unique": 0,
		"insert_after": "mobile_created_at",
	},
]


def _ensure_mobile_uuid_field(doctype: str) -> None:
	if not frappe.db.exists("DocType", doctype):
		return

	meta = frappe.get_meta(doctype, cached=True)
	existing_custom = {
		row.fieldname: row.name
		for row in frappe.get_all(
			"Custom Field",
			filters={"dt": doctype, "fieldname": ["in", [f["fieldname"] for f in _MOBILE_CUSTOM_FIELDS]]},
			fields=["name", "fieldname"],
		)
	}

	for spec in _MOBILE_CUSTOM_FIELDS:
		fieldname = spec["fieldname"]

		if meta.has_field(fieldname):
			continue

		if fieldname in existing_custom:
			frappe.db.set_value(
				"Custom Field",
				existing_custom[fieldname],
				{k: v for k, v in spec.items() if k not in ("insert_after", "fieldname")},
				update_modified=False,
			)
		else:
			frappe.get_doc({"doctype": "Custom Field", "dt": doctype, **spec}).insert(ignore_permissions=True)


def update_doctype_meta_modified(doc: Document, method: str | None = None) -> None:
	doctype_name = _get_doctype_name_from_doc(doc)
	if not doctype_name:
		return

	rows = frappe.get_all(
		"Mobile Configuration Form",
		filters={
			"parenttype": "Mobile Configuration",
			"parentfield": "table_lwis",
			"mobile_workspace_item": doctype_name,
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
