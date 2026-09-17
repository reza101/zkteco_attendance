"""ZKTeco ADMS push-protocol receiver for the UA300 attendance device.

The UA300 firmware only lets you configure a Server Address + Port on the
device itself — the request path is fixed to /iclock/... by the firmware —
so this is wired in via a custom page_renderer (see page_renderer.py)
instead of the usual /api/method/ convention, which the device can't reach.

Device -> here -> Employee Checkin. branch_sync (if installed) then carries
Employee Checkin on to the center automatically; nothing here needs to know
whether this site is the branch or the center.
"""

import frappe

# ATTLOG "state" column. HRMS Employee Checkin.log_type only has IN/OUT, so
# Break/Overtime states collapse onto whichever side they belong to.
LOG_TYPE_MAP = {
	"0": "IN",   # Check In
	"1": "OUT",  # Check Out
	"2": "OUT",  # Break Out
	"3": "IN",   # Break In
	"4": "IN",   # Overtime In
	"5": "OUT",  # Overtime Out
}


def handle_cdata_get():
	"""Device handshake: GET /iclock/cdata?SN=...&options=all"""
	sn = frappe.form_dict.get("SN")
	_touch_device(sn)
	return (
		f"GET OPTION FROM: {sn}\n"
		"Stamp=9999\n"
		"OpStamp=0\n"
		"ErrorDelay=60\n"
		"Delay=30\n"
		"TransFlag=1111000000\n"
		"TransInterval=1\n"
		"TransTables=ATTLOG OPERLOG\n"
		"Realtime=1\n"
		"Encrypt=0\n"
	)


def handle_cdata_post():
	"""Device pushes data: POST /iclock/cdata?SN=...&table=ATTLOG"""
	sn = frappe.form_dict.get("SN")
	table = (frappe.form_dict.get("table") or "").upper()
	_touch_device(sn)

	if not _is_device_allowed(sn):
		frappe.log_error(
			title="ADMS: rejected unknown device SN",
			message=f"SN={sn} table={table}. Set Zkteco Attendance Settings."
			f"device_serial_number to this value once confirmed genuine.",
		)
		return "OK"

	if table == "ATTLOG":
		body = frappe.local.request.get_data(as_text=True) or ""
		_process_attlog(sn, body)

	# OPERLOG and other tables (enrollment/admin changes) are ack'd but not processed.
	return "OK"


def handle_getrequest():
	"""Device polls for pending commands: GET /iclock/getrequest?SN=..."""
	_touch_device(frappe.form_dict.get("SN"))
	return "OK"


def handle_devicecmd():
	"""Device reports command execution results: POST /iclock/devicecmd?SN=..."""
	_touch_device(frappe.form_dict.get("SN"))
	return "OK"


def _process_attlog(sn, body):
	for line in body.splitlines():
		line = line.strip()
		if not line:
			continue
		try:
			columns = line.split("\t")
			if len(columns) < 3:
				continue
			pin, time_str, status = columns[0], columns[1], columns[2]
			_create_checkin(pin, time_str, status, sn)
		except Exception:
			# One malformed/unexpected line must not drop the rest of the batch.
			frappe.log_error(title="ADMS: failed to process ATTLOG line", message=f"SN={sn} line={line!r}")


def _create_checkin(pin, time_str, status, sn):
	employee = frappe.db.get_value("Employee", {"attendance_device_id": pin}, "name")
	if not employee:
		frappe.log_error(
			title="ADMS: unmapped device user",
			message=f"Device PIN {pin!r} from SN={sn} has no Employee with a matching "
			f"Attendance Device ID. Punch at {time_str} was dropped.",
		)
		return

	log_type = LOG_TYPE_MAP.get(status, "IN")

	if frappe.db.exists("Employee Checkin", {
		"employee": employee,
		"time": time_str,
		"log_type": log_type,
	}):
		return  # device retransmit of a punch we already recorded

	doc = frappe.new_doc("Employee Checkin")
	doc.employee = employee
	doc.log_type = log_type
	doc.time = time_str
	doc.device_id = f"ZKT-{sn}"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()


def _is_device_allowed(sn):
	settings = frappe.get_single("Zkteco Attendance Settings")
	if not settings.enabled:
		return False
	configured = (settings.device_serial_number or "").strip()
	# Empty = not configured yet (initial setup/testing) — accept any device.
	return not configured or configured == sn


def _touch_device(sn):
	# Best-effort connectivity monitoring — must never block acking the device.
	try:
		frappe.db.set_value(
			"Zkteco Attendance Settings", None,
			{"last_seen_at": frappe.utils.now(), "last_sn_seen": sn},
			update_modified=False,
		)
		frappe.db.commit()
	except Exception:
		pass
