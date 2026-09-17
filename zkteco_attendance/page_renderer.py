from werkzeug.wrappers import Response

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer


class ADMSPageRenderer(BaseRenderer):
	"""Handles the fixed /iclock/... paths the ZKTeco ADMS protocol requires.

	Registered via the page_renderer hook (see hooks.py) rather than the usual
	/api/method/ convention — the device firmware can't be pointed at anything
	but /iclock/<action>.
	"""

	def can_render(self):
		return self.path.startswith("iclock/")

	def render(self):
		from zkteco_attendance import adms

		action = self.path.split("/", 1)[1] if "/" in self.path else ""
		method = frappe.local.request.method

		try:
			if action == "cdata" and method == "GET":
				body = adms.handle_cdata_get()
			elif action == "cdata" and method == "POST":
				body = adms.handle_cdata_post()
			elif action == "getrequest":
				body = adms.handle_getrequest()
			elif action == "devicecmd":
				body = adms.handle_devicecmd()
			else:
				body = "OK"
		except Exception:
			# The device retries/queues on anything but a plain "OK" — always
			# ack it and investigate failures via the Error Log instead.
			frappe.log_error(title="ADMS: unhandled error")
			body = "OK"

		return Response(body, status=200, mimetype="text/plain")
