import frappe
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Mobile Configuration Form"
TABLE = f"tab{DOCTYPE}"
OLD = "doctype_meta_modifed_at"
NEW = "doctype_meta_modified_at"


def execute():
	if not frappe.db.has_column(DOCTYPE, OLD):
		return

	if frappe.db.has_column(DOCTYPE, NEW):
		frappe.db.sql(
			f"UPDATE `{TABLE}` SET `{NEW}` = `{OLD}` " f"WHERE `{NEW}` IS NULL AND `{OLD}` IS NOT NULL"
		)
		frappe.db.sql_ddl(f"ALTER TABLE `{TABLE}` DROP COLUMN IF EXISTS `{OLD}`")
	else:
		rename_field(DOCTYPE, OLD, NEW)

	frappe.db.commit()
