# mobile_control/api/helpers/permissions.py

"""User permissions helpers."""

from typing import Any

import frappe

from .mobile_config import get_mobile_configuration_payload


def _has_doctype_permission(doctype: str, ptype: str, user: str) -> bool:
	"""Check permission with enforcement and return boolean."""
	try:
		frappe.has_permission(doctype, ptype, user=user, throw=True)
		return True
	except frappe.PermissionError:
		return False


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
						"read": _has_doctype_permission(workspace_item, "read", user.name),
						"write": _has_doctype_permission(workspace_item, "write", user.name),
						"create": _has_doctype_permission(workspace_item, "create", user.name),
						"delete": _has_doctype_permission(workspace_item, "delete", user.name),
						"submit": _has_doctype_permission(workspace_item, "submit", user.name),
						"cancel": _has_doctype_permission(workspace_item, "cancel", user.name),
						"amend": _has_doctype_permission(workspace_item, "amend", user.name),
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
