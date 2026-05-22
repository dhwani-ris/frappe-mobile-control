import frappe


def execute():
	"""Default offline_enabled to 0 on the existing Mobile Configuration single.

	`Mobile Configuration` is a Single (issingle=1) — it has no `tabMobile
	Configuration` MySQL table, so `frappe.db.has_column(...)` raises
	`TableMissingError`. Use the meta to check the field instead, and skip
	cleanly when the DocType isn't synced yet (fresh install of mobile_control
	on a site where the DocType row doesn't exist).

	Preserves any value an admin has already set; only writes 0 when no value
	is stored in `tabSingles` yet.
	"""
	if not frappe.db.exists("DocType", "Mobile Configuration"):
		return

	meta = frappe.get_meta("Mobile Configuration")
	if not meta.has_field("offline_enabled"):
		return

	if frappe.db.get_single_value("Mobile Configuration", "offline_enabled") is not None:
		return

	frappe.db.set_single_value("Mobile Configuration", "offline_enabled", 0)
	frappe.db.commit()
