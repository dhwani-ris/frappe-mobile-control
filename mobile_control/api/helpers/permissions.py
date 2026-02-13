# mobile_control/api/helpers/permissions.py

"""User permissions helpers."""

from typing import Any

import frappe

from .mobile_config import get_mobile_configuration_payload


def get_user_permissions(user: Any) -> dict[str, Any]:
	"""Get user permissions including roles and doctype permissions."""
	try:
		roles = frappe.get_roles(user.name)
		permissions: dict[str, dict[str, bool]] = {}

		# Get mobile configuration doctypes to check permissions for
		mobile_config = get_mobile_configuration_payload().get("configuration", [])
		mobile_doctypes = [row.get("mobile_doctype") for row in mobile_config if row.get("mobile_doctype")]

		# Get permissions for each mobile doctype
		for doctype in mobile_doctypes:
			if doctype:
				permissions[doctype] = {
					"read": frappe.has_permission(doctype, "read", user=user.name),
					"write": frappe.has_permission(doctype, "write", user=user.name),
					"create": frappe.has_permission(doctype, "create", user=user.name),
					"delete": frappe.has_permission(doctype, "delete", user=user.name),
					"submit": frappe.has_permission(doctype, "submit", user=user.name),
					"cancel": frappe.has_permission(doctype, "cancel", user=user.name),
					"amend": frappe.has_permission(doctype, "amend", user=user.name),
				}

		return {
			"roles": roles,
			"permissions": permissions,
		}
	except Exception as e:
		frappe.log_error(f"Error fetching user permissions: {e}")
		return {
			"roles": [],
			"permissions": {},
		}
