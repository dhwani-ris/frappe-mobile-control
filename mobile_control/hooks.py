app_name = "mobile_control"
app_title = "Mobile Control"
app_publisher = "DHWANI RIS"
app_description = "Mobile Control - Custom Frappe Application"
app_email = "frappeteam@dhwaniris.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "mobile_control",
# 		"logo": "/assets/mobile_control/logo.png",
# 		"title": "Mobile Control",
# 		"route": "/mobile_control",
# 		"has_permission": "mobile_control.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mobile_control/css/mobile_control.css"
# app_include_js = "/assets/mobile_control/js/mobile_control.js"

# include js, css files in header of web template
# web_include_css = "/assets/mobile_control/css/mobile_control.css"
# web_include_js = "/assets/mobile_control/js/mobile_control.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "mobile_control/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "mobile_control/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "mobile_control.utils.jinja_methods",
# 	"filters": "mobile_control.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "mobile_control.install.before_install"
# after_install = "mobile_control.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "mobile_control.uninstall.before_uninstall"
# after_uninstall = "mobile_control.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "mobile_control.utils.before_app_install"
# after_app_install = "mobile_control.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "mobile_control.utils.before_app_uninstall"
# after_app_uninstall = "mobile_control.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mobile_control.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }
doc_events = {
	"DocType": {
		"on_update": "mobile_control.mobile_control.doctype.mobile_configuration.mobile_configuration.update_doctype_meta_modified",
	},
	"Custom Field": {
		"on_update": "mobile_control.mobile_control.doctype.mobile_configuration.mobile_configuration.update_doctype_meta_modified",
		"on_trash": "mobile_control.mobile_control.doctype.mobile_configuration.mobile_configuration.update_doctype_meta_modified",
	},
	"Property Setter": {
		"on_update": "mobile_control.mobile_control.doctype.mobile_configuration.mobile_configuration.update_doctype_meta_modified",
		"on_trash": "mobile_control.mobile_control.doctype.mobile_configuration.mobile_configuration.update_doctype_meta_modified",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": ["mobile_control.tasks.cleanup_mobile_refresh_tokens"],
}

# Testing
# -------

# before_tests = "mobile_control.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"mobile_auth.login": "mobile_control.api.api_auth.login",
	"mobile_auth.logout": "mobile_control.api.api_auth.logout",
	"mobile_auth.send_login_otp": "mobile_control.api.api_auth.send_mobile_otp",
	"mobile_auth.verify_login_otp": "mobile_control.api.api_auth.verify_mobile_otp",
	"mobile_auth.refresh_token": "mobile_control.api.api_auth.refresh_token",
	"mobile_auth.app_status": "mobile_control.api.api_auth.get_mobile_app_status",
	"mobile_auth.configuration": "mobile_control.api.api_auth.get_mobile_configuration",
	"mobile_auth.permissions": "mobile_control.api.api_auth.get_user_permissions",
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "mobile_control.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = ["mobile_control.api.jwt_auth.token_auth_middleware"]
# after_request = ["mobile_control.utils.after_request"]

# Job Events
# ----------
# before_job = ["mobile_control.utils.before_job"]
# after_job = ["mobile_control.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"mobile_control.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# Fixtures
# --------
fixtures = [{"doctype": "Role", "filters": {"name": ["in", ["Mobile User"]]}}]
