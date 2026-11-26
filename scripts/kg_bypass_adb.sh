#!/bin/bash
# FRP Freedom — Samsung Knox Guard Bypass via ADB + AppOps
# Prerequisites: ADB must be enabled on the target device (via QR code method)
# Based on: https://xdaforums.com/t/guide-bypass-knox-guard-kg-on-sm-a042f-android-14-via-adb-appops.4796541
# Tested on Android 14, works on devices originally released with Android 9+

set -e

echo "=== FRP Freedom — Samsung KG Bypass (ADB + AppOps) ==="
echo ""

# Check ADB connection
echo "Checking ADB connection..."
if ! adb get-state 2>/dev/null; then
    echo "✗ No ADB device found. Enable ADB first via QR code method."
    echo "  1. Connect phone to WiFi"
    echo "  2. On KG lock screen, double-tap center → QR scanner"
    echo "  3. Scan the QR code at ~/frp-bot/tools/adb_enable_qr.png"
    echo "  4. Wait for ADB enabler APK to install"
    echo "  5. Re-run this script"
    exit 1
fi

echo "✓ ADB device connected: $(adb get-state)"
echo ""

# Read device info
echo "=== Device Info ==="
adb shell getprop ro.product.model 2>/dev/null && echo "(model)"
adb shell getprop ro.build.version.release 2>/dev/null && echo "(android)"
adb shell getprop ro.build.version.security_patch 2>/dev/null && echo "(SPL)"
echo ""

# Step 1: Break KG enforcement
echo "=== Step 1: Breaking KG enforcement ==="
adb shell settings put global device_provisioned 0
echo "  ✓ Set device_provisioned=0"
adb shell settings put secure user_setup_complete 0
echo "  ✓ Set user_setup_complete=0"
echo ""

# Step 2: Reboot
echo "=== Step 2: Rebooting (KG will be gone after reboot) ==="
echo "  After reboot, run this script again with --post-reboot flag"
echo "  to block EMM reactivation."
adb reboot
exit 0
