#!/usr/bin/env python3
"""Tests for FRP Bot core functionality"""

import pytest

from core.detector import DeviceInfo, identify_chipset
from core.method_selector import MethodSelector
from tools.wrappers import ExecutionResult, get_executor


class TestChipsetIdentification:
    """Test chipset family identification from device properties"""

    def test_mediatek_patterns(self):
        dev = DeviceInfo(chipset="mt6789", brand="xiaomi", model="Redmi Note 11")
        assert identify_chipset(dev) == "mediatek"

        dev = DeviceInfo(chipset="helio_g99", brand="motorola")
        assert identify_chipset(dev) == "mediatek"

        dev = DeviceInfo(chipset="dimensity_1080", brand="realme")
        assert identify_chipset(dev) == "mediatek"

    def test_qualcomm_patterns(self):
        dev = DeviceInfo(chipset="snapdragon_8gen1", brand="oneplus")
        assert identify_chipset(dev) == "qualcomm"

        dev = DeviceInfo(chipset="msm8998", brand="google")
        assert identify_chipset(dev) == "qualcomm"

        dev = DeviceInfo(chipset="qcom", brand="sony")
        assert identify_chipset(dev) == "qualcomm"

    def test_exynos_patterns(self):
        dev = DeviceInfo(chipset="exynos2100", brand="samsung")
        assert identify_chipset(dev) == "exynos"

        dev = DeviceInfo(chipset="s5e9925", brand="samsung")
        assert identify_chipset(dev) == "exynos"

    def test_kirin_patterns(self):
        dev = DeviceInfo(chipset="kirin710", brand="huawei")
        assert identify_chipset(dev) == "kirin"

        dev = DeviceInfo(chipset="hi6260", brand="honor")
        assert identify_chipset(dev) == "kirin"

    def test_unisoc_patterns(self):
        dev = DeviceInfo(chipset="ums9230", brand="tecno")
        assert identify_chipset(dev) == "unisoc"

        dev = DeviceInfo(chipset="t606", brand="itel")
        assert identify_chipset(dev) == "unisoc"

    def test_connection_type_fallback(self):
        # EDL mode implies Qualcomm
        dev = DeviceInfo(connection_type="edl", chipset="")
        assert identify_chipset(dev) == "qualcomm"

        # BROM mode implies MediaTek
        dev = DeviceInfo(connection_type="brom", chipset="")
        assert identify_chipset(dev) == "mediatek"

        # Download mode implies Samsung
        dev = DeviceInfo(connection_type="download", chipset="")
        assert identify_chipset(dev) == "exynos|snapdragon"


class TestMethodSelector:
    """Test method selection and ranking"""

    def setup_method(self):
        self.selector = MethodSelector()

    def test_samsung_usa_2024(self):
        methods = self.selector.select_methods({
            "brand": "samsung",
            "model": "SM-G991U",
            "chipset": "exynos2100",
            "connection_type": "adb",
            "security_patch": "2024-05-01",
            "region": "usa",
        })
        assert len(methods) > 0
        # nPhoneKIT 2024 should be highest priority
        assert methods[0].tool == "nphonekit"
        assert methods[0].function == "frp_unlock_2024"

    def test_samsung_2022_2023(self):
        methods = self.selector.select_methods({
            "brand": "samsung",
            "model": "SM-G998U",
            "chipset": "exynos2100",
            "connection_type": "adb",
            "security_patch": "2022-10-01",
        })
        assert len(methods) > 0
        assert methods[0].tool == "nphonekit"
        assert methods[0].function == "frp_unlock_2022_2023"

    def test_samsung_pre_2022(self):
        methods = self.selector.select_methods({
            "brand": "samsung",
            "model": "SM-G973U",
            "chipset": "exynos9820",
            "connection_type": "adb",
            "security_patch": "2022-01-01",
        })
        assert len(methods) > 0
        assert methods[0].tool == "nphonekit"
        assert methods[0].function == "frp_unlock_pre2022"

    def test_mediatek_brom(self):
        methods = self.selector.select_methods({
            "brand": "xiaomi",
            "model": "Redmi Note 11",
            "chipset": "mt6789",
            "connection_type": "brom",
            "security_patch": "2023-08-01",
        })
        assert len(methods) > 0
        assert methods[0].tool == "mtkclient"
        assert methods[0].function == "erase_partitions"

    def test_kirin_710_fastboot(self):
        methods = self.selector.select_methods({
            "brand": "huawei",
            "model": "P30 Lite",
            "chipset": "kirin710",
            "connection_type": "fastboot",
            "security_patch": "2020-12-01",
        })
        assert len(methods) > 0
        assert methods[0].tool == "kirin_toolkit"
        assert methods[0].function == "fastboot_ram_hijack"

    def test_unisoc_termux(self):
        methods = self.selector.select_methods({
            "brand": "tecno",
            "model": "Pop 2F",
            "chipset": "mt6761",
            "connection_type": "brom",
            "security_patch": "2019-12-01",
            "platform": "termux",
        })
        assert len(methods) > 0
        # Note: chipset is mediatek so mtkclient wins, but if unisoc:
        methods = self.selector.select_methods({
            "brand": "tecno",
            "model": "Pop 2F",
            "chipset": "ums9230",
            "connection_type": "brom",
            "security_patch": "2019-12-01",
            "platform": "termux",
        })
        assert methods[0].tool == "spd_client"


class TestExecutors:
    """Test executor availability"""

    def test_mtkclient_executor(self):
        exe = get_executor("mtkclient")
        assert exe is not None
        assert exe.binary_path is not None

    def test_edl_executor(self):
        exe = get_executor("edl")
        assert exe is not None
        assert exe.binary_path is not None

    def test_nphonekit_executor(self):
        exe = get_executor("nphonekit")
        assert exe is not None

    def test_frp_freedom_executor(self):
        exe = get_executor("frp_freedom")
        assert exe is not None

    def test_kirin_toolkit_executor(self):
        exe = get_executor("kirin_toolkit")
        assert exe is not None

    def test_spd_client_executor(self):
        exe = get_executor("spd_client")
        assert exe is not None

    def test_unknown_executor(self):
        exe = get_executor("nonexistent_tool")
        assert exe is None


class TestExecutionResult:
    """Test ExecutionResult dataclass"""

    def test_default_artifacts(self):
        result = ExecutionResult(True, "out", "err", 1.0)
        assert result.artifacts == []

    def test_custom_artifacts(self):
        result = ExecutionResult(True, "out", "err", 1.0, ["backup.img"])
        assert result.artifacts == ["backup.img"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
