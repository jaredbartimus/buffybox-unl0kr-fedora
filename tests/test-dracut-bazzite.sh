#!/usr/bin/env bash
#
# Synthetic dracut composition test inside a Bazzite Deck container.
# Validates Bazzite userspace/dracut integration without requiring host kernel/hardware.
#
set -euo pipefail
export LC_ALL=C

workdir="${1:-/tmp/work}"
img="${workdir}/test-unl0kr.img"

echo "::: Verifying unl0kr dracut module presence in Bazzite userspace..."
module_setup="/usr/lib/dracut/modules.d/55unl0kr/module-setup.sh"
if [ ! -f "$module_setup" ]; then
  echo "FAIL: $module_setup not found on system"
  exit 1
fi
echo "  ok   $module_setup exists"

echo "::: Verifying dracut is available from unl0kr-dracut dependencies..."
if ! command -v dracut >/dev/null 2>&1; then
  echo "FAIL: dracut missing after installing unl0kr-dracut and its dependencies" >&2
  exit 1
fi
echo "  ok   dracut command is available"
echo "::: Dracut version: $(dracut --version 2>&1 | head -n1)"

mkdir -p "$workdir"

echo "::: Constructing synthetic Bazzite initramfs at ${img}..."
# Note: Stock dracut in Fedora/Bazzite may emit a non-fatal diagnostic
# "dracut-install: ERROR: installing '/root'" due to stock dracut handling of
# the /root directory. The test requires dracut to return exit code 0.
dracut \
  --no-kernel \
  --no-hostonly \
  --no-uefi \
  --add unl0kr \
  --force "$img"

echo "::: Inspecting synthetic Bazzite initramfs..."
out=$(lsinitrd "$img")

pass=0
fail=0

check_in() {
  if echo "$out" | grep "$1" >/dev/null; then
    echo "  ok   $1"
    pass=$((pass + 1))
  else
    echo "  FAIL $1 missing"
    fail=$((fail + 1))
  fi
}

check_not_in() {
  if ! echo "$out" | grep "$1" >/dev/null; then
    echo "  ok   does not contain $1"
    pass=$((pass + 1))
  else
    echo "  FAIL $1 present"
    fail=$((fail + 1))
  fi
}

echo "== Initramfs payload assertions =="
check_in "usr/bin/unl0kr"
check_in "usr/libexec/unl0kr-agent"
check_in "etc/unl0kr.conf"
check_in "usr/lib/systemd/system/unl0kr-agent.path"
check_in "usr/lib/systemd/system/unl0kr-agent.service"
check_in "etc/systemd/system/paths.target.wants/unl0kr-agent.path"
check_in "usr/share/libinput"
check_in "usr/lib/udev/rules.d/80-libinput-device-groups.rules"
check_in "usr/lib/udev/rules.d/90-libinput-fuzz-override.rules"
check_in "usr/share/X11/xkb"
check_in "lib.*/libinih.so"
check_in "lib.*/libinput.so"

check_not_in "card1"

echo "test-dracut-bazzite: $pass ok, $fail failed"
[ "$fail" -eq 0 ]
