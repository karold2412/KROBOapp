"""Tests for check-server-laptop.sh on fake /sys and /proc trees with stub commands.

Run: python3 -m unittest discover -s scripts/tests
"""

import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check-server-laptop.sh"
# Only these system tools are visible to the script; the rest (lsblk, docker...) are
# stubs, so the result does not depend on the machine running the test.
SYSTEM_TOOLS = ["awk", "sed", "grep", "cat", "head", "basename", "sh", "bash"]


class FakeLaptop:
    def __init__(self, base):
        self.root = Path(base) / "root"
        self.bin = Path(base) / "bin"
        self.bin.mkdir(parents=True)
        self.sysbin = Path(base) / "sysbin"
        self.sysbin.mkdir()
        for tool in SYSTEM_TOOLS:
            (self.sysbin / tool).symlink_to(shutil.which(tool))
        self.write("etc/os-release", 'PRETTY_NAME="Linux Mint 22.2"\n')

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def command(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{shutil.which('sh')}\n" + textwrap.dedent(body))
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def run(self):
        env = {
            "PATH": f"{self.bin}:{self.sysbin}",
            "KROBO_CHECK_ROOT": str(self.root),
        }
        return subprocess.run([shutil.which("bash"), str(SCRIPT)], capture_output=True, text=True, env=env)


def good_laptop(base):
    laptop = FakeLaptop(base)
    laptop.write("proc/meminfo", "MemTotal:       16123456 kB\n")
    laptop.write("sys/class/tpm/tpm0/tpm_version_major", "2\n")
    laptop.write("sys/class/power_supply/BAT0/type", "Battery\n")
    laptop.write("sys/class/power_supply/BAT0/charge_control_end_threshold", "80\n")
    laptop.write("sys/class/net/enp3s0/device/vendor", "0x8086\n")
    laptop.write("sys/class/net/enp3s0/carrier", "1\n")
    laptop.write("sys/class/net/wlp2s0/device/vendor", "0x8086\n")
    laptop.write("sys/class/net/wlp2s0/wireless/x", "")
    laptop.write("sys/class/net/wlp2s0/carrier", "1\n")
    laptop.command("findmnt", 'echo /dev/mapper/vgmint-root\n')
    laptop.command("lsblk", """\
        echo "lvm   0 vgmint-root"
        echo "crypt 0 nvme0n1p3_crypt"
        echo "part  0 nvme0n1p3"
        echo "disk  0 nvme0n1"
    """)
    laptop.command("smartctl", 'echo "SMART overall-health self-assessment test result: PASSED"\n')
    laptop.command("df", """\
        echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
        echo "/dev/mapper/vgmint-root 900000000 100000000 800000000 12% /"
    """)
    laptop.command("systemd-analyze", """\
        echo "[Login]"
        echo "#HandleLidSwitch=suspend"
        echo "HandleLidSwitch=ignore"
        echo "HandleLidSwitchExternalPower=ignore"
    """)
    laptop.command("systemctl", """\
        case "$2" in
            docker) echo enabled ;;
            *) echo masked ;;
        esac
    """)
    laptop.command("timedatectl", """\
        case "$3" in
            NTPSynchronized) echo yes ;;
            Timezone) echo Europe/Warsaw ;;
        esac
    """)
    laptop.command("docker", """\
        if [ "$1" = "compose" ]; then echo "Docker Compose version v5.6.1"; else echo "Docker version 29.9.2"; fi
    """)
    laptop.command("id", 'echo 0\n')
    return laptop


class CheckServerLaptopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_ready_laptop_passes(self):
        result = good_laptop(self.tmp.name).run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("[FAIL]", result.stdout)
        self.assertNotIn("[WARN]", result.stdout)
        for text in [
            "RAM: 15.4 GiB",
            "TPM 2.0 present",
            "System disk encrypted (LUKS)",
            "Disk nvme0n1 is an SSD",
            "SMART for /dev/nvme0n1: PASSED",
            "Free disk space: 819 GB",
            "Battery charge limit: 80%",
            "Closing the lid does not suspend",
            "System sleep disabled",
            "Ethernet connected (enp3s0)",
            "Clock synchronized",
            "Docker starts with the system",
            "Result: OK 14, WARN 0, FAIL 0",
        ]:
            self.assertIn(text, result.stdout)

    def test_unprepared_laptop_lists_every_gap(self):
        laptop = good_laptop(self.tmp.name)
        laptop.write("proc/meminfo", "MemTotal:        3900000 kB\n")
        (laptop.root / "sys/class/tpm/tpm0/tpm_version_major").unlink()
        (laptop.root / "sys/class/power_supply/BAT0/charge_control_end_threshold").unlink()
        (laptop.root / "sys/class/net/enp3s0/device/vendor").unlink()
        (laptop.root / "sys/class/net/enp3s0/device").rmdir()
        laptop.command("lsblk", """\
            echo "part 1 sda2"
            echo "disk 1 sda"
        """)
        laptop.command("smartctl", 'echo "SMART overall-health self-assessment test result: FAILED!"\n')
        laptop.command("systemd-analyze", 'echo "[Login]"\n')
        laptop.command("systemctl", """\
            case "$2" in
                docker) echo disabled ;;
                *) echo enabled ;;
            esac
        """)
        laptop.command("timedatectl", """\
            case "$3" in
                NTPSynchronized) echo no ;;
                Timezone) echo UTC ;;
            esac
        """)
        result = laptop.run()
        self.assertEqual(result.returncode, 1)
        for text in [
            "[FAIL]    RAM: 3.7 GiB",
            "[FAIL]    No TPM 2.0",
            "[FAIL]    System disk is not encrypted",
            "[FAIL]    Disk sda is a spinning disk",
            "[FAIL]    SMART for /dev/sda did not report PASSED",
            "[FAIL]    The laptop does not expose a battery charge limit",
            "[FAIL]    Closing the lid suspends the laptop (HandleLidSwitch=suspend, on mains power: suspend)",
            "[FAIL]    Sleep is not disabled: sleep.target suspend.target hibernate.target hybrid-sleep.target",
            "[FAIL]    No Ethernet adapter",
            "[FAIL]    Clock is not synchronized",
            "[WARN]    System time zone: UTC",
            "[FAIL]    Docker does not start with the system",
        ]:
            self.assertIn(text, result.stdout)

    def test_threshold_at_100_is_a_warning(self):
        laptop = good_laptop(self.tmp.name)
        laptop.write("sys/class/power_supply/BAT0/charge_control_end_threshold", "100\n")
        result = laptop.run()
        self.assertEqual(result.returncode, 0)
        self.assertIn("[WARN]    Battery charge limit set to 100%", result.stdout)

    def test_lid_ignored_only_on_battery_is_not_enough(self):
        laptop = good_laptop(self.tmp.name)
        laptop.command("systemd-analyze", """\
            echo "HandleLidSwitch=ignore"
            echo "HandleLidSwitchExternalPower=suspend"
        """)
        result = laptop.run()
        self.assertIn("[FAIL]    Closing the lid suspends the laptop", result.stdout)

    def test_cable_unplugged_is_a_warning(self):
        laptop = good_laptop(self.tmp.name)
        laptop.write("sys/class/net/enp3s0/carrier", "0\n")
        result = laptop.run()
        self.assertIn("[WARN]    Ethernet port without a cable: enp3s0", result.stdout)

    def test_without_root_smart_is_skipped_with_hint(self):
        laptop = good_laptop(self.tmp.name)
        laptop.command("id", 'echo 1000\n')
        result = laptop.run()
        self.assertIn("[WARN]    SMART not checked: run the script with sudo", result.stdout)

    def test_missing_docker(self):
        laptop = good_laptop(self.tmp.name)
        (laptop.bin / "docker").unlink()
        result = laptop.run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("[FAIL]    Docker missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
