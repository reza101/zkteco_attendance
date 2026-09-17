app_name = "zkteco_attendance"
app_title = "Zkteco Attendance"
app_publisher = "webmajors"
app_description = "ZKTeco ADMS attendance device integration for ERPNext HR"
app_email = "webmajors.com@gmail.com"
app_license = "Proprietary"

after_install = "zkteco_attendance.install.after_install"

# Handles the fixed /iclock/cdata, /iclock/getrequest, /iclock/devicecmd
# paths the ZKTeco ADMS protocol pushes to — see page_renderer.py.
page_renderer = [
    "zkteco_attendance.page_renderer.ADMSPageRenderer",
]

fixtures = [
    {"dt": "Module Def", "filters": [["name", "=", "Zkteco Attendance"]]},
]

# Pulls from BioTime's REST API (see biotime_sync.py); no-ops unless
# Zkteco Attendance Settings.biotime_sync_enabled is checked.
scheduler_events = {
    "cron": {
        "*/10 * * * *": [
            "zkteco_attendance.biotime_sync.scheduled_sync",
        ],
    },
}
