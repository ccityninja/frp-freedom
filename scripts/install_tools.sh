#!/bin/bash
# FRP Bot — Tool Installation Script
# Run with: bash scripts/install_tools.sh
# Review each command before running!

set -euo pipefail

echo "=== FRP Bot Tool Installer ==="
echo "This script installs open-source FRP bypass tools."
echo "Run on Linux (Ubuntu 22.04+/Debian 12/Arch) or WSL2."
echo ""

# Check Python
PYTHON=$(command -v python3 || command -v python)
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: python3 not found"
    exit 1
fi
echo "Using Python: $($PYTHON --version)"

# Create venv
VENV_DIR="$HOME/frp-bot-venv"
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment at $VENV_DIR"
    $PYTHON -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install core Python tools
echo ""
echo "=== Installing Python tools ==="

# mtkclient (MediaTek)
echo "Installing mtkclient..."
pip install mtkclient

# edl (Qualcomm)
echo "Installing edl..."
pip install edl

# nPhoneCLI (Samsung)
echo "Installing nPhoneCLI..."
pip install git+https://github.com/nlckysolutions/nPhoneCLI

# frp-freedom (Multi-OEM)
echo "Installing frp-freedom..."
pip install git+https://github.com/youngrichu/frp-freedom

# SPDClient (Unisoc) - for Linux
echo "Installing SPDClient..."
pip install spdclient

echo ""
echo "=== Cloning Git repositories (GUI/tools) ==="

# Kirin Toolkit
KIRIN_DIR="$HOME/huawei_kirin_toolkit"
if [[ ! -d "$KIRIN_DIR" ]]; then
    echo "Cloning huawei_kirin_toolkit..."
    git clone https://github.com/FrgfA4ftfzTdfyyyr5f6tESD3/huawei_kirin_toolkit "$KIRIN_DIR"
    cd "$KIRIN_DIR" && pip install -r requirements.txt
else
    echo "huawei_kirin_toolkit already exists, pulling updates..."
    cd "$KIRIN_DIR" && git pull
fi

# MTK Studio (GUI for mtkclient)
MTK_STUDIO_DIR="$HOME/mtk-studio"
if [[ ! -d "$MTK_STUDIO_DIR" ]]; then
    echo "Cloning mtk-studio..."
    git clone https://github.com/sukitanzil23/mtk-studio "$MTK_STUDIO_DIR"
    cd "$MTK_STUDIO_DIR" && pip install -r requirements.txt
else
    echo "mtk-studio already exists, pulling updates..."
    cd "$MTK_STUDIO_DIR" && git pull
fi

# Samsung FRP Bypass WEB
SAMSUNG_WEB_DIR="$HOME/Samsung-FRP-Bypass-WEB"
if [[ ! -d "$SAMSUNG_WEB_DIR" ]]; then
    echo "Cloning Samsung-FRP-Bypass-WEB..."
    git clone https://github.com/NDXCode/Samsung-FRP-Bypass-WEB "$SAMSUNG_WEB_DIR"
else
    echo "Samsung-FRP-Bypass-WEB already exists, pulling updates..."
    cd "$SAMSUNG_WEB_DIR" && git pull
fi

# F.U_frp (Samsung + MTK)
FU_FRP_DIR="$HOME/F.U_frp"
if [[ ! -d "$FU_FRP_DIR" ]]; then
    echo "Cloning F.U_frp..."
    git clone https://github.com/blackarched/F.U_frp "$FU_FRP_DIR"
    cd "$FU_FRP_DIR" && pip install -r requirements.txt 2>/dev/null || true
else
    echo "F.U_frp already exists, pulling updates..."
    cd "$FU_FRP_DIR" && git pull
fi

echo ""
echo "=== Installing system dependencies (Linux) ==="

# Detect distro
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    DISTRO=$ID
else
    DISTRO="unknown"
fi

case $DISTRO in
    ubuntu|debian)
        echo "Installing udev rules, usbdk, adb, fastboot..."
        sudo apt update
        sudo apt install -y android-tools-adb android-tools-fastboot python3-usb libusb-1.0-0-dev

        # MTK udev rules
        if [[ -f "$HOME/mtkclient/Drivers/51-mtk.rules" ]]; then
            sudo cp "$HOME/mtkclient/Drivers/51-mtk.rules" /etc/udev/rules.d/
            echo "Installed MTK udev rules"
        elif [[ -f "$HOME/.local/lib/python3.*/site-packages/mtkclient/Drivers/51-mtk.rules" ]]; then
            sudo cp "$HOME/.local/lib/python3.*/site-packages/mtkclient/Drivers/51-mtk.rules" /etc/udev/rules.d/
            echo "Installed MTK udev rules from site-packages"
        fi

        # EDL udev rules
        if [[ -f "$HOME/edl/Drivers/51-edl.rules" ]]; then
            sudo cp "$HOME/edl/Drivers/51-edl.rules" /etc/udev/rules.d/
            echo "Installed EDL udev rules"
        elif [[ -f "$HOME/.local/lib/python3.*/site-packages/edl/Drivers/51-edl.rules" ]]; then
            sudo cp "$HOME/.local/lib/python3.*/site-packages/edl/Drivers/51-edl.rules" /etc/udev/rules.d/
            echo "Installed EDL udev rules from site-packages"
        fi

        # Android udev rules (generic)
        if [[ -f "$HOME/edl/Drivers/50-android.rules" ]]; then
            sudo cp "$HOME/edl/Drivers/50-android.rules" /etc/udev/rules.d/
        fi

        sudo udevadm control --reload-rules
        sudo udevadm trigger
        ;;

    arch|manjaro)
        echo "Installing via pacman..."
        sudo pacman -S --needed android-tools android-udev python-pyusb libusb
        # MTK/EDL rules via AUR or manual
        ;;

    fedora)
        echo "Installing via dnf..."
        sudo dnf install -y android-tools python3-pyusb libusbx-devel
        ;;

    *)
        echo "Unknown distro: $DISTRO — install adb, fastboot, python3-usb, libusb manually"
        ;;
esac

echo ""
echo "=== Installing frp-bot itself ==="
BOT_DIR="$HOME/frp-bot"
if [[ -d "$BOT_DIR" ]]; then
    cd "$BOT_DIR" && pip install -e .
else
    echo "frp-bot directory not found at $BOT_DIR"
    echo "Clone it first: git clone <repo> $BOT_DIR"
fi

echo ""
echo "=== Installation Complete ==="
echo ""
echo "To use frp-bot:"
echo "  source $VENV_DIR/bin/activate"
echo "  frp-bot detect"
echo "  frp-bot methods"
echo "  frp-bot bypass"
echo ""
echo "Key tools installed:"
echo "  mtkclient        : MediaTek BROM/DA FRP erase"
echo "  edl              : Qualcomm EDL/Sahara/Firehose"
echo "  nPhoneCLI        : Samsung AT modem exploits (2022-2024)"
echo "  frp-freedom      : Multi-OEM ADB/hardware exploits"
echo "  kirin_toolkit    : Huawei Kirin 710 fastboot RAM hijack"
echo "  mtk-studio       : GUI for mtkclient"
echo "  SPDClient        : Unisoc/Spreadtrum (Termux/Linux)"
echo ""
echo "Hardware tier (when software fails):"
echo "  Z3X Easy JTAG Plus  : \$559+  (eMMC/UFS/JTAG/ISP)"
echo "  UFI Box             : \$316-500 (Samsung UFS FRP)"
echo "  Medusa Pro 2        : \$369-439 (ISP/UFS/eMMC)"
echo "  Testpoint Box       : \$23    (cable-style testpoint)"
echo ""
echo "Remember: ONLY run on devices you own or have explicit written authorization for."