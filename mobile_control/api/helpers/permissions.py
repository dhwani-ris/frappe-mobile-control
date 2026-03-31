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
		mobile_workspace_items = [
			row.get("mobile_workspace_item") for row in mobile_config if row.get("mobile_workspace_item")
		]

		for workspace_item in mobile_workspace_items:
			if workspace_item:
				permissions_list.append(
					{
						"doctype": workspace_item,
						"read": frappe.has_permission(workspace_item, "read", user=user.name),
						"write": frappe.has_permission(workspace_item, "write", user=user.name),
						"create": frappe.has_permission(workspace_item, "create", user=user.name),
						"delete": frappe.has_permission(workspace_item, "delete", user=user.name),
						"submit": frappe.has_permission(workspace_item, "submit", user=user.name),
						"cancel": frappe.has_permission(workspace_item, "cancel", user=user.name),
						"amend": frappe.has_permission(workspace_item, "amend", user=user.name),
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
