import hashlib

from frappe.model.document import Document


def device_log_name(user: str, device_id: str | None) -> str:
	"""Deterministic name for a user's device row.

	Two racing logins from the same phone then collide on the primary key instead
	of each inserting its own row.
	"""
	return hashlib.sha256(f"{user}::{device_id or ''}".encode()).hexdigest()[:20]


class MobileDeviceLog(Document):
	def autoname(self) -> None:
		self.name = device_log_name(self.user, self.device_id)
