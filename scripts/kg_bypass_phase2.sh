#!/bin/bash
# FRP Freedom — Samsung KG Bypass Phase 2 (Post-Reboot EMM Blocking)
# Run this AFTER the first reboot from kg_bypass_adb.sh
# This blocks EMM packages from reactivating the KG lock

set -e

echo "=== FRP Freedom — KG Bypass Phase 2 (EMM Blocking) ==="
echo ""

if ! adb get-state 2>/dev/null; then
    echo "✗ No ADB device found. Reconnect USB and authorize ADB."
    exit 1
fi

echo "✓ ADB device connected"
echo ""

# Step 3: Block EMM packages via AppOps
echo "=== Step 3: Blocking EMM packages via AppOps ==="

# Samsung EMM agent
EMM1="com.sds.emm.cloud.knox.samsung"
# Samsung MDM client
EMM2="com.sec.enterprise.knox.cloudmdm.smdms"

for pkg in "$EMM1" "$EMM2"; do
    echo "  Blocking $pkg..."
    adb shell appops set "$pkg" RUN_ANY_IN_BACKGROUND deny 2>/dev/null || echo "    (RUN_ANY_IN_BACKGROUND - skipped)"
    adb shell appops set "$pkg" RUN_IN_BACKGROUND deny 2>/dev/null || echo "    (RUN_IN_BACKGROUND - skipped)"
    adb shell appops set "$pkg" START_FOREGROUND deny 2>/dev/null || echo "    (START_FOREGROUND - skipped)"
    adb shell appops set "$pkg" WAKE_LOCK deny 2>/dev/null || echo "    (WAKE_LOCK - skipped)"
    echo "    ✓ Blocked"
done

echo ""

# Step 4: Restore provisioned state
echo "=== Step 4: Restoring provisioned state ==="
adb shell settings put global device_provisioned 1
echo "  ✓ Set device_provisioned=1"
adb shell settings put secure user_setup_complete 1
echo "  ✓ Set user_setup_complete=1"
echo ""

# Step 5: Disable OTA to prevent KG re-lock
echo "=== Step 5: Disabling OTA updates ==="
adb shell settings put global package_verifier_enable 0 2>/dev/null && echo "  ✓ Disabled package verifier"
adb shell pm disable com.wssyncmldm 2>/dev/null && echo "  ✓ Disabled wssyncmldm (OTA)" || echo "  (wssyncmldm already disabled or not found)"
echo ""

echo "=== KG Bypass Complete! ==="
echo "Reboot the phone to verify KG is gone."
echo "If KG reappears, the RPMB state may need hardware ISP reset."
echo ""
echo "Rebooting device..."
adb reboot
