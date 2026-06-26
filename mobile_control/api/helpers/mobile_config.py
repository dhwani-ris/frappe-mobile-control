# mobile_control/api/helpers/mobile_config.py

"""Mobile configuration helpers."""

from typing import Any

import frappe


def _meta_modified_for(form_doctype: str, fallback: Any) -> str:
	"""Derive the mobile meta-refresh signal for a form: MAX(modified) across its
	DocType + child DocTypes + Property Setters + Custom Fields. Customize-Form
	artifacts don't bump DocType.modified, so without this the signal is stale.

	Reuses the same helper that stamps the meta response in rf_mis (single source of
	truth, so the device's cached `modified` converges with this signal and it does
	not re-fetch every launch). Falls back to the manually-stored value if rf_mis is
	unavailable or the form doctype is missing.
	"""
	if not form_doctype:
		return fallback or ""
	try:
		from rf_mis.rf_mis.api.meta_override import compute_meta_modified

		derived = compute_meta_modified(form_doctype)
		if derived:
			return derived
	except Exception:
		pass
	return fallback or ""


def get_mobile_configuration_payload() -> dict[str, Any]:
	"""Get mobile configuration and app status from Single doctype."""
	try:
		config = frappe.get_single("Mobile Configuration")
		configuration: list[dict[str, Any]] = []
		if config.table_lwis:
			for row in config.table_lwis:
				configuration.append(
					{
						# `mobile_doctype` is the key the SDK actually reads
						# (mobile_form_name.dart). `mobile_workspace_item` is kept for
						# server-side consumers (permissions.py). Both carry the form
						# doctype name.
						"mobile_doctype": row.mobile_workspace_item,
						"mobile_workspace_item": row.mobile_workspace_item,
						"group_name": row.workspace_group_name or "",
						"doctype_meta_modifed_at": _meta_modified_for(
							row.mobile_workspace_item, row.doctype_meta_modifed_at
						),
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
