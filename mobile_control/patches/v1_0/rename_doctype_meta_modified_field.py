# Rename the misspelled child-table field `doctype_meta_modifed_at` ->
# `doctype_meta_modified_at` on `Mobile Configuration Form`.
#
# Runs in [post_model_sync]: by then `sync_all()` has already created the new
# (empty) column, and frappe does NOT auto-drop the old column, so both exist.
# `rename_field` copies old -> new (it does not ALTER/drop), so we drop the
# now-redundant misspelled column afterwards.

import frappe
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Mobile Configuration Form"
OLD = "doctype_meta_modifed_at"
NEW = "doctype_meta_modified_at"


def execute():
	# Nothing to do on a fresh install (only the corrected column exists) or if
	# already migrated.
	if not frappe.db.has_column(DOCTYPE, OLD):
		return

	# Copies data OLD -> NEW and updates reports / property setters / user settings.
	rename_field(DOCTYPE, OLD, NEW)

	# rename_field only copies; remove the leftover misspelled column. Use
	# DROP ... IF EXISTS rather than a has_column() guard: frappe.db.has_column
	# can serve a stale cached column list immediately after DDL, which would
	# wrongly skip the drop.
	frappe.db.sql_ddl(f"ALTER TABLE `tab{DOCTYPE}` DROP COLUMN IF EXISTS `{OLD}`")
	frappe.db.commit()
