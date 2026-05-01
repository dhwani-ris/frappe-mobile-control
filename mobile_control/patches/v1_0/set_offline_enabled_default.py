import frappe


def execute():
	"""Default offline_enabled to 0 on the existing Mobile Configuration single.

	No-op on fresh installs (the column already defaults to 0). Idempotent
	on reruns.
	"""
	if not frappe.db.has_column("Mobile Configuration", "offline_enabled"):
		return
	frappe.db.set_single_value("Mobile Configuration", "offline_enabled", 0)
	frappe.db.commit()
