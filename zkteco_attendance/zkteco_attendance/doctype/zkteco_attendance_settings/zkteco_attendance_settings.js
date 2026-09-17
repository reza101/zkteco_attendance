frappe.ui.form.on("Zkteco Attendance Settings", {
	refresh(frm) {
		if (!frm.doc.biotime_sync_enabled) {
			return;
		}

		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "zkteco_attendance.biotime_sync.test_connection",
				freeze: true,
				callback: () => frappe.msgprint(__("Connected to BioTime successfully.")),
			});
		});

		frm.add_custom_button(__("Sync Now"), () => {
			frappe.call({
				method: "zkteco_attendance.biotime_sync.trigger_sync",
				freeze: true,
				callback: (r) => {
					frappe.msgprint(r.message);
					frm.reload_doc();
				},
			});
		});
	},
});
