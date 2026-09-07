#!/usr/bin/env bash
set -euo pipefail

rpmdir="${1:-build/RPMS}"
img="/tmp/test-unl0kr.img"

echo "::: Installing rpms for dracut test..."
dnf install -y dracut
# Install all unl0kr rpms built locally (avoiding debuginfo for this test)
find "$rpmdir" -name 'unl0kr-*.rpm' ! -name '*-debuginfo-*.rpm' ! -name '*-debugsource-*.rpm' -exec rpm -ivh --force {} +

echo "::: Constructing test initramfs..."
dracut \
  --no-kernel \
  --no-hostonly \
  --no-uefi \
  --add unl0kr \
  --force "$img"

echo "::: Inspecting test initramfs..."
out=$(lsinitrd "$img")

pass=0 fail=0
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

echo "test-dracut-image: $pass ok, $fail failed"
[ "$fail" -eq 0 ]
