#!/bin/bash
# FRP Bot — Organized Tool Downloader
# Downloads each tool to its own clearly-named folder
# Run: bash scripts/download_tools.sh

set -euo pipefail

BASE_DIR="$HOME/frp-tools"
mkdir -p "$BASE_DIR"

echo "=== FRP Tool Downloader ==="
echo "Target directory: $BASE_DIR"
echo ""

# Function to clone or update a repo
clone_or_pull() {
    local repo_url="$1"
    local target_dir="$2"
    local friendly_name="$3"

    if [[ -d "$target_dir/.git" ]]; then
        echo "[$friendly_name] Updating existing repo..."
        cd "$target_dir" && git pull --quiet
    else
        echo "[$friendly_name] Cloning..."
        git clone --quiet "$repo_url" "$target_dir"
    fi
    echo "[$friendly_name] Done → $target_dir"
}

# Function to pip install a package
pip_install() {
    local pkg="$1"
    local friendly_name="$2"
    echo "[$friendly_name] Installing via pip..."
    pip install --quiet "$pkg"
    echo "[$friendly_name] Done"
}

echo "=== Python-based tools (pip) ==="

# mtkclient - MediaTek BROM/Preloader
pip_install "mtkclient" "mtkclient"

# edl - Qualcomm EDL/Sahara/Firehose
pip_install "edl" "edl"

# nPhoneKIT - Samsung FRP (includes mtkclient as dep)
pip_install "git+https://github.com/nlckysolutions/nPhoneCLI" "nphonekit"

# frp-freedom - Multi-OEM ADB/Download/EDL exploits
pip_install "git+https://github.com/youngrichu/frp-freedom" "frp-freedom"

# SPDClient - Unisoc/Spreadtrum
pip_install "spdclient" "spdclient"

echo ""
echo "=== Git repositories (GUI/tools/source) ==="

# Kirin Toolkit - Huawei Kirin 710 fastboot RAM hijack
clone_or_pull \
    "https://github.com/FrgfA4ftfzTdfyyyr5f6tESD3/huawei_kirin_toolkit" \
    "$BASE_DIR/kirin-toolkit" \
    "kirin-toolkit"

# MTK Studio - GUI for mtkclient
clone_or_pull \
    "https://github.com/sukitanzil23/mtk-studio" \
    "$BASE_DIR/mtk-studio" \
    "mtk-studio"

# Samsung FRP Bypass WEB - Web-based Samsung exploit
clone_or_pull \
    "https://github.com/NDXCode/Samsung-FRP-Bypass-WEB" \
    "$BASE_DIR/samsung-frp-web" \
    "samsung-frp-web"

# F.U_frp - Samsung + MTK FRP
clone_or_pull \
    "https://github.com/blackarched/F.U_frp" \
    "$BASE_DIR/fu-frp" \
    "fu-frp"

# nPhoneKIT source (for reference/development)
clone_or_pull \
    "https://github.com/nlckysolutions/nPhoneKIT" \
    "$BASE_DIR/nphonekit-source" \
    "nphonekit-source"

# mtkclient source (for reference/development)
clone_or_pull \
    "https://github.com/bkerler/mtkclient" \
    "$BASE_DIR/mtkclient-source" \
    "mtkclient-source"

# edl source (for reference/development)
clone_or_pull \
    "https://github.com/bkerler/edl" \
    "$BASE_DIR/edl-source" \
    "edl-source"

# frp-freedom source
clone_or_pull \
    "https://github.com/youngrichu/frp-freedom" \
    "$BASE_DIR/frp-freedom-source" \
    "frp-freedom-source"

# SPD Research Tool (Unisoc)
clone_or_pull \
    "https://github.com/alexmyc/SPDResearchTool" \
    "$BASE_DIR/spd-research-tool" \
    "spd-research-tool"

# Samsung FRP Tools collection
clone_or_pull \
    "https://github.com/Barra44/Samsung-FRP-Tools" \
    "$BASE_DIR/samsung-frp-tools" \
    "samsung-frp-tools"

# MTK Auth Bypass (newer exploits)
clone_or_pull \
    "https://github.com/MTKAuthBypass/MTKAuthBypass" \
    "$BASE_DIR/mtk-auth-bypass" \
    "mtk-auth-bypass"

# Qualcomm Firehose collection
clone_or_pull \
    "https://github.com/tc75-firehose/firehose" \
    "$BASE_DIR/qualcomm-firehose" \
    "qualcomm-firehose"

# Unisoc/SPD flash tools
clone_or_pull \
    "https://github.com/sheroy/spd-flasher" \
    "$BASE_DIR/spd-flasher" \
    "spd-flasher"

echo ""
echo "=== Installing Python dependencies for cloned repos ==="

# Install deps for repos that have requirements.txt
for req in \
    "$BASE_DIR/kirin-toolkit/requirements.txt" \
    "$BASE_DIR/mtk-studio/requirements.txt" \
    "$BASE_DIR/fu-frp/requirements.txt" \
    "$BASE_DIR/nphonekit-source/requirements.txt" \
    "$BASE_DIR/mtkclient-source/requirements.txt" \
    "$BASE_DIR/edl-source/requirements.txt" \
    "$BASE_DIR/frp-freedom-source/requirements.txt" \
    "$BASE_DIR/spd-research-tool/requirements.txt" \
    "$BASE_DIR/samsung-frp-tools/requirements.txt" \
    "$BASE_DIR/mtk-auth-bypass/requirements.txt" \
; do
    if [[ -f "$req" ]]; then
        echo "Installing deps from $req"
        pip install --quiet -r "$req" 2>/dev/null || true
    fi
done

echo ""
echo "=== Creating tool index ==="

cat > "$BASE_DIR/TOOL_INDEX.md" << 'EOF'
# FRP Tools Index
Generated: $(date)

## Python Packages (installed via pip)
| Tool | Folder | Purpose | Chipset |
|------|--------|---------|---------|
| mtkclient | `~/.local/lib/python*/site-packages/mtkclient` | MediaTek BROM/Preloader FRP erase | MediaTek |
| edl | `~/.local/lib/python*/site-packages/edl` | Qualcomm EDL/Sahara/Firehose | Qualcomm |
| nphonekit | `~/.local/lib/python*/site-packages/nphonekit` | Samsung AT modem FRP unlock | Samsung/Exynos |
| frp-freedom | `~/.local/lib/python*/site-packages/frp_freedom` | Multi-OEM ADB/Download/EDL | Samsung, MTK, QC |
| spdclient | `~/.local/lib/python*/site-packages/spdclient` | Unisoc Download mode | Unisoc |

## Source Repositories (cloned to ~/frp-tools/)
| Folder | Tool | Purpose | Chipset |
|--------|------|---------|---------|
| `kirin-toolkit/` | huawei_kirin_toolkit | Kirin 710 fastboot RAM hijack | Kirin 710 |
| `mtk-studio/` | mtk-studio | GUI for mtkclient (PyWebView) | MediaTek |
| `samsung-frp-web/` | Samsung-FRP-Bypass-WEB | Web-based Samsung FRP | Samsung |
| `fu-frp/` | F.U_frp | Samsung + MTK FRP scripts | Samsung, MTK |
| `nphonekit-source/` | nPhoneKIT | Samsung FRP reference source | Samsung |
| `mtkclient-source/` | mtkclient | MediaTek reference source | MediaTek |
| `edl-source/` | edl | Qualcomm reference source | Qualcomm |
| `frp-freedom-source/` | frp-freedom | Multi-OEM reference source | Multi |
| `spd-research-tool/` | SPDResearchTool | Unisoc research/debug | Unisoc |
| `samsung-frp-tools/` | Samsung-FRP-Tools | Samsung FRP tool collection | Samsung |
| `mtk-auth-bypass/` | MTKAuthBypass | MediaTek auth bypass exploits | MediaTek V6 |
| `qualcomm-firehose/` | firehose | Qualcomm firehose collection | Qualcomm |
| `spd-flasher/` | spd-flasher | Unisoc flash tool | Unisoc |

## Quick Commands
```bash
# MediaTek FRP erase (BROM mode)
python -m mtkclient e frp,persist

# Qualcomm FRP erase (EDL mode)
python -m edl erase frp

# Samsung FRP unlock (ADB + modem)
python -m nphonekit frp_unlock_2024

# Multi-OEM FRP freedom
python -m frp_freedom --help

# Unisoc FRP erase
python -m spdclient erase --partition frp
```

## Hardware Tools (not downloaded - purchase separately)
| Tool | Price | Capability |
|------|-------|------------|
| Z3X Easy JTAG Plus | $559+ | eMMC/UFS/JTAG/ISP |
| UFI Box | $316-500 | Samsung UFS FRP |
| Medusa Pro 2 | $369-439 | ISP/UFS/eMMC |
| Testpoint Box | $23 | Cable-style testpoint |
EOF

echo ""
echo "=== Done! ==="
echo "Tools installed to: $BASE_DIR"
echo "Index written to: $BASE_DIR/TOOL_INDEX.md"
echo ""
echo "Quick test:"
echo "  python -m mtkclient --help"
echo "  python -m edl --help"
echo "  python -m nphonekit --help"