# mobile_control/api/helpers/mobile_config.py

"""Mobile configuration helpers."""

from typing import Any

import frappe


def get_mobile_configuration_payload() -> dict[str, Any]:
	"""Get mobile configuration and app status from Single doctype."""
	try:
		config = frappe.get_single("Mobile Configuration")
		configuration: list[dict[str, Any]] = []
		if config.table_lwis:
			for row in config.table_lwis:
				configuration.append(
					{
						"mobile_workspace_item": row.mobile_workspace_item,
						"group_name": row.group_name or "",
						"doctype_meta_modifed_at": row.doctype_meta_modifed_at or "",
						"doctype_icon": row.doctype_icon or "",
						"order": row.order or 0,
					}
				)
		enabled = bool(config.enabled)
		maintenance_mode = bool(config.maintenance_mode)
		return {
			"enabled": enabled,
			"package_name": config.package_name if enabled else "",
			"version": config.minimum_app_version if enabled else "",
			"maintenance_mode": maintenance_mode,
			"maintenance_message": config.maintenance_message if maintenance_mode else "",
			"configuration": configuration,
		}
	except Exception:
		frappe.log_error(f"Error fetching mobile configuration: {frappe.get_traceback()}")
		return {
			"enabled": False,
			"package_name": "",
			"version": "",
			"maintenance_mode": False,
			"maintenance_message": "",
			"configuration": [],
		}
