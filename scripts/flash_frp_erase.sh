#!/bin/bash
# FRP Freedom — Samsung PERSISTENT+METADATA erase via Heimdall
# This MUST be the FIRST USB operation after a fresh download mode enumeration.
# No prior pyusb, no heimdall detect, no heimdall print-pit.
# Usage: bash flash_frp_erase.sh

set -e

PERSISTENT_ZEROS="$HOME/frp-bot/backups/persistent_zeros.bin"
METADATA_ZEROS="$HOME/frp-bot/backups/metadata_zeros.bin"
HEIMDALL="/tmp/heimdall-extracted/usr/bin/heimdall"

echo "=== FRP Freedom — Samsung FRP Erase ==="
echo "Target: PERSISTENT + METADATA partitions (zeroed)"
echo "Mode: Download mode (04e8:685d)"
echo ""

# Wait for device
echo "Watching for Samsung download mode..."
for i in $(seq 1 60); do
    DEV=$(lsusb 2>&1 | grep "04e8:685d")
    if [ -n "$DEV" ]; then
        echo "FOUND at attempt $i: $DEV"
        echo ""
        echo "Flashing IMMEDIATELY (first and only operation)..."
        echo ""
        "$HEIMDALL" flash \
            --PERSISTENT "$PERSISTENT_ZEROS" \
            --METADATA "$METADATA_ZEROS" \
            --no-reboot \
            --stdout-errors 2>&1
        EXIT=$?
        echo ""
        echo "Heimdall exit code: $EXIT"
        if [ $EXIT -eq 0 ]; then
            echo "✓✓✓ FRP ERASE SUCCESSFUL — reboot the phone to check ✓✓✓"
        else
            echo "✗ Flash failed — see error above"
        fi
        exit $EXIT
    fi
    sleep 1
done
echo "Device not found after 60 seconds"
exit 1
