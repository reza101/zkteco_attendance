"""Pull-based sync from a ZKTeco BioTime server's REST API into Employee Checkin.

Used when the device is (and stays) configured to push to a BioTime server
rather than directly to this site — see adms.py's docstring for the direct-push
alternative. Both mechanisms share the same Employee mapping (attendance_device_id)
and dedup rule, so a device can be migrated between them without double-counting.
"""

import frappe
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from zkteco_attendance.adms import LOG_TYPE_MAP

TOKEN_PATH = "/jwt-api-token-auth/"
TRANSACTIONS_PATH = "/iclock/api/transactions/"
PAGE_SIZE = 200
# Re-pull a small window before the last checkpoint so a transaction that
# lands mid-page on one run isn't skipped on the next.
OVERLAP_MINUTES = 10

# BioTime sits behind Cloudflare, which occasionally drops a request from a
# non-browser client (RemoteDisconnected) — retry transient network/5xx
# failures a few times before giving up. A browser-like UA also avoids
# being flagged by bot-detection that a bare "python-requests/x.x" UA can trip.
USER_AGENT = "Mozilla/5.0 (compatible; ERPNextBioTimeSync/1.0)"


def _session():
	session = requests.Session()
	retry = Retry(
		total=3,
		backoff_factor=1,
		status_forcelist=(429, 500, 502, 503, 504),
		allowed_methods=frozenset(["GET", "POST"]),
	)
	adapter = HTTPAdapter(max_retries=retry)
	session.mount("https://", adapter)
	session.mount("http://", adapter)
	session.headers.update({"User-Agent": USER_AGENT})
	return session


def scheduled_sync():
	settings = frappe.get_single("Zkteco Attendance Settings")
	if not settings.biotime_sync_enabled:
		return
	sync(settings)


@frappe.whitelist()
def trigger_sync():
	frappe.only_for(("System Manager", "HR Manager"))
	settings = frappe.get_single("Zkteco Attendance Settings")
	return sync(settings)


@frappe.whitelist()
def test_connection():
	frappe.only_for(("System Manager", "HR Manager"))
	settings = frappe.get_single("Zkteco Attendance Settings")
	try:
		_get_token(settings)
	except Exception as e:
		frappe.throw(str(e))
	return "ok"


def sync(settings):
	try:
		token = _get_token(settings)
		start_time = _get_start_time(settings)
		count = _pull_transactions(settings, token, start_time)
		status = f"OK — {count} transaction(s) processed"
		_update_status(settings, status)
		return status
	except Exception:
		frappe.log_error(title="BioTime sync failed")
		_update_status(settings, "Failed — see Error Log")
		raise


def _get_token(settings):
	url = (settings.biotime_url or "").rstrip("/") + TOKEN_PATH
	password = settings.get_password("biotime_password")
	response = _session().post(
		url,
		json={"username": settings.biotime_username, "password": password},
		timeout=30,
	)
	response.raise_for_status()
	return response.json()["token"]


def _get_start_time(settings):
	if settings.biotime_last_sync_at:
		return frappe.utils.add_to_date(settings.biotime_last_sync_at, minutes=-OVERLAP_MINUTES)
	# No checkpoint yet (first run, or reset for a newly-mapped employee) —
	# fall back to the configured floor instead of pulling full history.
	return settings.biotime_sync_start_date or None


def _pull_transactions(settings, token, start_time):
	base_url = (settings.biotime_url or "").rstrip("/") + TRANSACTIONS_PATH
	session = _session()
	headers = {"Authorization": f"JWT {token}"}
	params = {"page_size": PAGE_SIZE, "ordering": "punch_time"}
	if start_time:
		params["start_time"] = frappe.utils.get_datetime_str(start_time)

	url, count, latest_punch_time = base_url, 0, start_time
	while url:
		response = session.get(url, headers=headers, params=params, timeout=60)
		response.raise_for_status()
		payload = response.json()

		for txn in payload.get("data", []):
			if _create_checkin(txn):
				count += 1
			if txn.get("punch_time"):
				latest_punch_time = max(latest_punch_time or txn["punch_time"], txn["punch_time"])

		url = payload.get("next")
		# BioTime sits behind Cloudflare TLS termination and isn't configured
		# to know the original request was HTTPS, so DRF's paginated `next`
		# link comes back as http:// — force https so we don't drop to plaintext.
		if url and url.startswith("http://"):
			url = "https://" + url[len("http://"):]
		params = None  # `next` already carries the query string

	if latest_punch_time:
		frappe.db.set_value(
			"Zkteco Attendance Settings", None,
			"biotime_last_sync_at", latest_punch_time,
			update_modified=False,
		)
	frappe.db.commit()
	return count


def _create_checkin(txn):
	emp_code = txn.get("emp_code")
	punch_time = txn.get("punch_time")
	if not emp_code or not punch_time:
		return False

	employee = frappe.db.get_value("Employee", {"attendance_device_id": emp_code}, "name")
	if not employee:
		frappe.log_error(
			title="BioTime sync: unmapped device user",
			message=f"BioTime emp_code {emp_code!r} has no Employee with a matching "
			f"Attendance Device ID. Punch at {punch_time} was dropped.",
		)
		return False

	log_type = LOG_TYPE_MAP.get(str(txn.get("punch_state")), "IN")

	if frappe.db.exists("Employee Checkin", {
		"employee": employee,
		"time": punch_time,
		"log_type": log_type,
	}):
		return False

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee
	doc.log_type = log_type
	doc.time = punch_time
	doc.device_id = f"BioTime-{txn.get('terminal_sn') or ''}"
	doc.insert(ignore_permissions=True)
	return True


def _update_status(settings, status):
	frappe.db.set_value(
		"Zkteco Attendance Settings", None,
		"biotime_last_sync_status", status,
		update_modified=False,
	)
	frappe.db.commit()
