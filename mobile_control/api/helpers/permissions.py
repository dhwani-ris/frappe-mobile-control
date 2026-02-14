# mobile_control/api/helpers/permissions.py

"""User permissions helpers."""

from typing import Any

import frappe

from .mobile_config import get_mobile_configuration_payload


def get_user_permissions(user: Any) -> dict[str, Any]:
	"""Get user permissions: roles array and permissions array (one object per doctype)."""
	try:
		roles = frappe.get_roles(user.name)
		permissions_list: list[dict[str, Any]] = []

		mobile_config = get_mobile_configuration_payload().get("configuration", [])
		mobile_doctypes = [row.get("mobile_doctype") for row in mobile_config if row.get("mobile_doctype")]

		for doctype in mobile_doctypes:
			if doctype:
				permissions_list.append(
					{
						"doctype": doctype,
						"read": frappe.has_permission(doctype, "read", user=user.name),
						"write": frappe.has_permission(doctype, "write", user=user.name),
						"create": frappe.has_permission(doctype, "create", user=user.name),
						"delete": frappe.has_permission(doctype, "delete", user=user.name),
						"submit": frappe.has_permission(doctype, "submit", user=user.name),
						"cancel": frappe.has_permission(doctype, "cancel", user=user.name),
						"amend": frappe.has_permission(doctype, "amend", user=user.name),
					}
				)

		return {
			"roles": roles,
			"permissions": permissions_list,
		}
	except Exception as e:
		frappe.log_error(f"Error fetching user permissions: {e}")
		return {
			"roles": [],
			"permissions": [],
		}
