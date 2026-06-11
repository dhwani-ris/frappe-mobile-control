import frappe
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Mobile Configuration Form"
OLD = "doctype_meta_modifed_at"
NEW = "doctype_meta_modified_at"


def execute():
	if not frappe.db.has_column(DOCTYPE, OLD):
		return

	rename_field(DOCTYPE, OLD, NEW)

	frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP COLUMN IF EXISTS `{OLD}`")
	frappe.db.commit()
