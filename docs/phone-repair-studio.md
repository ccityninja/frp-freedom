# Phone Repair Studio

Start the read-only workbench from the project directory:

```sh
./venv/bin/python -m app.workbench
```

Open [http://127.0.0.1:8485](http://127.0.0.1:8485) on the same computer. No phone is needed for the troubleshooting guides.

- **Live connection** uses `lsusb` and `adb devices -l` on the host. It checks when the page opens and again about every three seconds while the tab is visible. If debugging is off, open the page before plugging in so the workbench can flag a USB count change. This detects a change in USB peripherals, not the phone's identity; a charge-only cable may not register. The **Refresh connection** button runs the same check on demand.
- **Choose a task** switches between the Android health diagnostic and Android/iPhone troubleshooting guides. Detection never starts a diagnostic, backup, or repair by itself.
- **Read Android health** requires ADB and one unambiguous, already authorized transport. On an unlocked phone, enable USB debugging and approve only a computer you recognize. The report reads Android version, battery level, temperature, charging state, and available space on `/data`. Missing readings are shown as unavailable. Charge level and temperature do not measure battery wear.
- The guides cover connectivity, charging, startup, storage, display, audio, backup, and official account recovery. iPhone support is guidance only; there is no iPhone telemetry or automatic backup.

This workbench does not flash firmware, erase data, send reports off the host, or collect personal files or device serials in the report.
