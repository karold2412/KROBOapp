#!/usr/bin/env bash
# Checks whether a laptop meets the KROBO primary server requirements (specification, section 12).
# Changes nothing on the system. Run with sudo for the most complete result (SMART):
#
#   sudo ./scripts/check-server-laptop.sh
#
# Exit code: 0 when there is no FAIL item, 1 when the laptop needs changes before use.
# KROBO_CHECK_ROOT lets the tests substitute fake /sys, /proc and /etc trees.

set -u
ROOT="${KROBO_CHECK_ROOT:-}"
LC_ALL=C
export LC_ALL

ok=0; warn=0; bad=0
result() {
    local status="$1"; shift
    case "$status" in
        OK) ok=$((ok + 1)); printf '[ OK ]    %s\n' "$*" ;;
        WARN) warn=$((warn + 1)); printf '[WARN]    %s\n' "$*" ;;
        FAIL) bad=$((bad + 1)); printf '[FAIL]    %s\n' "$*" ;;
        INFO) printf '[INFO]    %s\n' "$*" ;;
        MANUAL) printf '[MANUAL]  %s\n' "$*" ;;
    esac
}
have() { command -v "$1" >/dev/null 2>&1; }

echo "KROBO server laptop check"
echo

# Operating system
if [ -r "$ROOT/etc/os-release" ]; then
    # shellcheck source=/dev/null
    name="$(. "$ROOT/etc/os-release" && printf '%s' "${PRETTY_NAME:-unknown}")"
    result INFO "System: $name"
fi

# RAM: the specification requires 8 GB; the system reports slightly less than the nominal size.
mem_kb="$(awk '/^MemTotal:/ {print $2}' "$ROOT/proc/meminfo" 2>/dev/null)"
if [ -n "$mem_kb" ]; then
    mem_gib="$(awk -v kb="$mem_kb" 'BEGIN {printf "%.1f", kb / 1048576}')"
    if [ "$mem_kb" -ge 7340032 ]; then
        result OK "RAM: ${mem_gib} GiB"
    else
        result FAIL "RAM: ${mem_gib} GiB (at least 8 GB required)"
    fi
fi

# TPM 2.0: needed to unlock the encrypted disk automatically after a reboot.
tpm_file="$ROOT/sys/class/tpm/tpm0/tpm_version_major"
if [ -r "$tpm_file" ] && [ "$(cat "$tpm_file")" = "2" ]; then
    result OK "TPM 2.0 present"
else
    result FAIL "No TPM 2.0 (check that TPM/PTT/fTPM is enabled in the BIOS)"
fi

# System disk: LUKS encryption and SSD.
root_src=""
if have findmnt; then
    root_src="$(findmnt -no SOURCE / 2>/dev/null | head -n1)"
fi
if [ -n "$root_src" ] && have lsblk; then
    chain="$(lsblk -s -no TYPE,ROTA,NAME "$root_src" 2>/dev/null)"
    if printf '%s\n' "$chain" | awk '{print $1}' | grep -qx crypt; then
        result OK "System disk encrypted (LUKS)"
    else
        result FAIL "System disk is not encrypted (LUKS required; this usually means reinstalling the system)"
    fi
    disk_line="$(printf '%s\n' "$chain" | awk '$1 == "disk" {print; exit}')"
    disk_name="$(printf '%s' "$disk_line" | awk '{print $3}' | sed 's/^[^[:alnum:]]*//')"
    if [ "$(printf '%s' "$disk_line" | awk '{print $2}')" = "0" ]; then
        result OK "Disk ${disk_name:-(system)} is an SSD"
    else
        result FAIL "Disk ${disk_name:-(system)} is a spinning disk (HDD); the server needs an SSD"
    fi
    if have smartctl && [ "$(id -u)" = "0" ] && [ -n "$disk_name" ]; then
        if smartctl -H "/dev/$disk_name" 2>/dev/null | grep -q "PASSED"; then
            result OK "SMART for /dev/$disk_name: PASSED"
        else
            result FAIL "SMART for /dev/$disk_name did not report PASSED; inspect: sudo smartctl -a /dev/$disk_name"
        fi
    else
        result WARN "SMART not checked: run the script with sudo and install smartmontools"
    fi
else
    result WARN "Could not determine the system disk (findmnt/lsblk missing)"
fi

# Free space: five years of photos add up to hundreds of GB with several contractors.
avail_kb="$(df -Pk / 2>/dev/null | awk 'NR == 2 {print $4}')"
if [ -n "$avail_kb" ]; then
    avail_gb="$((avail_kb * 1024 / 1000000000))"
    if [ "$avail_gb" -ge 100 ]; then
        result OK "Free disk space: ${avail_gb} GB"
    else
        result WARN "Free disk space: ${avail_gb} GB (at least 100 GB recommended)"
    fi
fi

# Battery: constant charging to 100% wears out the cell.
threshold_file=""
for f in "$ROOT"/sys/class/power_supply/*/charge_control_end_threshold; do
    [ -e "$f" ] && threshold_file="$f" && break
done
battery_present=""
for f in "$ROOT"/sys/class/power_supply/*/type; do
    [ -r "$f" ] && [ "$(cat "$f")" = "Battery" ] && battery_present=1
done
if [ -n "$threshold_file" ]; then
    limit="$(cat "$threshold_file")"
    if [ "$limit" -le 90 ]; then
        result OK "Battery charge limit: ${limit}%"
    else
        result WARN "Battery charge limit set to ${limit}%; set 80% (e.g. TLP: STOP_CHARGE_THRESH_BAT0=80)"
    fi
elif [ -n "$battery_present" ]; then
    result FAIL "The laptop does not expose a battery charge limit to the system (check the BIOS or the vendor tool)"
else
    result INFO "No battery: charge limit does not apply"
fi

# Closed lid: a laptop on mains power must not suspend when the lid is closed.
if have systemd-analyze; then
    logind="$(systemd-analyze cat-config systemd/logind.conf 2>/dev/null)"
    lid="$(printf '%s\n' "$logind" | awk -F= '/^[[:space:]]*HandleLidSwitch=/ {v=$2} END {print v}')"
    lid_ac="$(printf '%s\n' "$logind" | awk -F= '/^[[:space:]]*HandleLidSwitchExternalPower=/ {v=$2} END {print v}')"
    lid="${lid:-suspend}"
    lid_ac="${lid_ac:-$lid}"
    if [ "$lid_ac" = "ignore" ] && [ "$lid" = "ignore" ]; then
        result OK "Closing the lid does not suspend the laptop"
    else
        result FAIL "Closing the lid suspends the laptop (HandleLidSwitch=$lid, on mains power: $lid_ac); set ignore"
    fi
fi

# System sleep: all sleep modes disabled (masked).
if have systemctl; then
    not_masked=""
    for target in sleep.target suspend.target hibernate.target hybrid-sleep.target; do
        state="$(systemctl is-enabled "$target" 2>/dev/null)"
        [ "$state" = "masked" ] || not_masked="$not_masked $target"
    done
    if [ -z "$not_masked" ]; then
        result OK "System sleep disabled"
    else
        result FAIL "Sleep is not disabled:$not_masked (sudo systemctl mask ...)"
    fi
fi

# Ethernet: a cable is more stable than Wi-Fi.
wired=""; wired_up=""
for dev in "$ROOT"/sys/class/net/*; do
    [ -e "$dev/device" ] || continue
    [ -e "$dev/wireless" ] || [ -e "$dev/phy80211" ] && continue
    name="$(basename "$dev")"
    wired="$wired $name"
    [ "$(cat "$dev/carrier" 2>/dev/null)" = "1" ] && wired_up="$name"
done
if [ -n "$wired_up" ]; then
    result OK "Ethernet connected ($wired_up)"
elif [ -n "$wired" ]; then
    result WARN "Ethernet port without a cable:$wired"
else
    result FAIL "No Ethernet adapter (a USB-Ethernet adapter is enough)"
fi

# Time: timestamps are evidence, so the clock must be synchronized.
if have timedatectl; then
    if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ]; then
        result OK "Clock synchronized (NTP)"
    else
        result FAIL "Clock is not synchronized (sudo timedatectl set-ntp true)"
    fi
    tz="$(timedatectl show -p Timezone --value 2>/dev/null)"
    if [ "$tz" = "Europe/Warsaw" ]; then
        result OK "Time zone Europe/Warsaw"
    else
        result WARN "System time zone: ${tz:-unknown} (the KROBO system uses Europe/Warsaw regardless)"
    fi
fi

# Docker: runs the services and starts with the system.
if have docker; then
    if docker compose version >/dev/null 2>&1; then
        result OK "Docker and Docker Compose installed ($(docker --version 2>/dev/null | head -n1))"
    else
        result FAIL "Docker Compose plugin missing (package docker-compose-plugin)"
    fi
    if have systemctl && [ "$(systemctl is-enabled docker 2>/dev/null)" = "enabled" ]; then
        result OK "Docker starts with the system"
    else
        result FAIL "Docker does not start with the system (sudo systemctl enable docker)"
    fi
else
    result FAIL "Docker missing (instructions: docs/stage-0.md, step 2)"
fi

result MANUAL "BIOS: power on when mains power is connected (Power On AC / Wake on AC)"
result MANUAL "The laptop stays at home permanently and is not used for daily work"

echo
echo "Result: OK $ok, WARN $warn, FAIL $bad"
[ "$bad" -eq 0 ]
