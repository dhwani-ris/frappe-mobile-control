# Copyright (c) 2026, Dhwani RIS and contributors
# For license information, please see license.txt

import frappe

DEFAULT_RETENTION_DAYS = 30


def after_install() -> None:
	"""Seed the Mobile Error Log retention default.

	bench install-app is non-interactive, so the 'ask at install' decision is
	realized as a settings field with a sensible default that an admin edits.
	"""
	current = frappe.db.get_single_value("Mobile Configuration", "mobile_error_log_retention_days")
	if not current:
		frappe.db.set_single_value(
			"Mobile Configuration",
			"mobile_error_log_retention_days",
			DEFAULT_RETENTION_DAYS,
		)
		frappe.db.commit()
