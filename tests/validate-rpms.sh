#!/usr/bin/env bash
#
# Post-build validation of the produced RPMs. Does NOT install anything.
#
# Usage: tests/validate-rpms.sh [RPMDIR]
#   RPMDIR  directory holding the binary RPMs (default: build/RPMS)
#
# Exit non-zero if any expectation fails. Intended to run inside the same
# fedora:44 container that built the packages (needs rpm, and for the last
# checks: cpio, binutils, systemd).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rpmdir="${1:-${repo_root}/build/RPMS}"
expdir="${repo_root}/tests/expected-files"
ver="$(sed -n 's/^Version:[[:space:]]*//p' "${repo_root}/buffybox-unl0kr.spec" | head -n1)"

pass=0 failn=0
ok()  { printf '  ok   %s\n' "$*"; pass=$((pass + 1)); }
bad() { printf '  FAIL %s\n' "$*"; failn=$((failn + 1)); }

# assert_ok "message" cmd...      -> ok if cmd succeeds, bad otherwise
assert_ok() { local m="$1"; shift; if "$@"; then ok "$m"; else bad "$m"; fi; }
# assert_no "message" cmd...      -> ok if cmd FAILS, bad if it succeeds
assert_no() { local m="$1"; shift; if "$@"; then bad "$m"; else ok "$m"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

rpm_of() {
	# print the single rpm path matching a glob under $rpmdir, else nothing
	local matches
	matches=$(find "$rpmdir" -maxdepth 1 -name "$1" | sort)
	[ "$(printf '%s\n' "$matches" | grep -c .)" -eq 1 ] && printf '%s\n' "$matches"
}

grep_q()  { grep -q "$@"; }                                   # wrappable predicates
req_has() { rpm -qp --requires "$1" | grep -q "^$2"; }
prov_has(){ rpm -qp --provides "$1" | grep -q "$2"; }

echo "== 1. expected package set =="
mapfile -t got < <(find "$rpmdir" -maxdepth 1 -name '*.rpm' -printf '%f\n' | sort)
for pat in "unl0kr-${ver}" "unl0kr-agent-${ver}" "unl0kr-debuginfo-${ver}" \
           "unl0kr-agent-debuginfo-${ver}" "buffybox-unl0kr-debugsource-${ver}"; do
	assert_ok "present: ${pat}-*" \
		grep_q "^${pat//./\\.}-" <<<"$(printf '%s\n' "${got[@]}")"
done
assert_no "no buffyboard/f0rmz rpm produced" \
	grep_q -iE 'buffyboard|f0rmz' <<<"$(printf '%s\n' "${got[@]}")"

echo "== 2. file lists (minus volatile /usr/lib/.build-id) =="
for pkg in unl0kr unl0kr-agent; do
	r=$(rpm_of "${pkg}-${ver}-*.rpm")
	if [ -z "$r" ]; then bad "cannot resolve exactly one rpm for ${pkg}"; continue; fi
	if diff -u "${expdir}/${pkg}.txt" \
		<(rpm -qpl "$r" | grep -v '^/usr/lib/\.build-id' | sort); then
		ok "${pkg} file list matches ${pkg}.txt"
	else
		bad "${pkg} file list differs from ${pkg}.txt"
	fi
done

echo "== 3. runtime deps of unl0kr =="
r=$(rpm_of "unl0kr-${ver}-*.rpm")
for so in libinput.so.10 libudev.so.1 libxkbcommon.so.0 libdrm.so.2 libinih.so; do
	assert_ok "requires ${so}" req_has "$r" "$so"
done

echo "== 4. bundled(lvgl) provide =="
assert_ok "unl0kr Provides bundled(lvgl)" prov_has "$r" '^bundled(lvgl) = '

echo "== 5. no setuid/setgid/file-caps anywhere =="
setid_hits=0
for r in "$rpmdir"/*.rpm; do
	while read -r mode caps path; do
		if (( (8#${mode} & 8#6000) != 0 )); then
			bad "setid bit: $path ($mode in $(basename "$r"))"; setid_hits=$((setid_hits + 1))
		fi
		if [ "$caps" != "(none)" ]; then
			bad "file caps on $path: $caps"; setid_hits=$((setid_hits + 1))
		fi
	done < <(rpm -qp --qf '[%{FILEMODES:octal} %{FILECAPS} %{FILENAMES}\n]' "$r")
done
[ "$setid_hits" -eq 0 ] && ok "no setid bits / no file caps in any rpm"

echo "== 6. scriptlets are only the systemd helpers =="
r=$(rpm_of "unl0kr-agent-${ver}-*.rpm")
scr=$(rpm -qp --scripts "$r")
assert_ok "agent scriptlets act on unl0kr-agent.path" \
	grep_q -E 'systemd-update-helper (install|remove)-system-units unl0kr-agent\.path' <<<"$scr"
assert_no "agent scriptlets contain no filesystem mutation / fetch" \
	grep_q -E '(^|[^a-z])(rm|mv|chmod|chown|useradd|groupadd|curl|wget)([^a-z]|$)' <<<"$scr"
r=$(rpm_of "unl0kr-${ver}-*.rpm")
assert_ok "unl0kr has no scriptlets" test -z "$(rpm -qp --scripts "$r")"

echo "== 7. unl0kr-agent baked-in binary path =="
if have cpio && have strings; then
	w=$(mktemp -d)
	( cd "$w" && rpm2cpio "$(rpm_of "unl0kr-agent-${ver}-*.rpm")" | cpio -idm --quiet )
	assert_ok "agent execs /usr/bin/unl0kr" \
		grep_q -x '/usr/bin/unl0kr' <(strings -a "$w/usr/libexec/unl0kr-agent")

	echo "== 8. systemd unit verification =="
	if have systemd-analyze; then
		mkdir -p "$w/units" /usr/libexec
		cp "$w"/usr/lib/systemd/system/unl0kr-agent.* "$w/units/"
		# stage the binary so 'verify' does not false-flag the ExecStart path
		install -m0755 "$w/usr/libexec/unl0kr-agent" /usr/libexec/unl0kr-agent
		export SYSTEMD_UNIT_PATH="$w/units:/usr/lib/systemd/system"
		assert_ok "unl0kr-agent.path verifies"    systemd-analyze verify "$w/units/unl0kr-agent.path"
		assert_ok "unl0kr-agent.service verifies" systemd-analyze verify "$w/units/unl0kr-agent.service"
	else
		echo "  skip: systemd-analyze not available"
	fi
	rm -rf "$w"
else
	echo "  skip: cpio/strings not available for baked-path + unit checks"
fi

echo
echo "validate-rpms: ${pass} ok, ${failn} failed"
[ "$failn" -eq 0 ]
