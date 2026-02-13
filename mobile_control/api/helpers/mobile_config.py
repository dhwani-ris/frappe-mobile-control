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
						"mobile_doctype": row.mobile_doctype,
						"group_name": row.group_name or "",
						"doctype_meta_modifed_at": row.doctype_meta_modifed_at or "",
						"doctype_icon": row.doctype_icon or "",
					}
				)
		enabled = bool(config.enabled)
		return {
			"enabled": enabled,
			"package_name": config.package_name if enabled else "",
			"app_title": config.app_name if enabled else "",
			"version": config.current_version if enabled else "",
			"configuration": configuration,
		}
	except Exception:
		return {
			"enabled": False,
			"package_name": "",
			"app_title": "",
			"version": "",
			"configuration": [],
		}
