#!/usr/bin/env bash
#
# Human-facing inspection of built RPMs WITHOUT installing them.
# Prints the standard query battery for every rpm in a directory and shows
# how to extract one for offline inspection.
#
# Usage: scripts/inspect-rpms.sh [RPMDIR]
#   RPMDIR  default: build/RPMS

set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rpmdir="${1:-${repo_root}/build/RPMS}"

shopt -s nullglob
rpms=("$rpmdir"/*.rpm)
[ "${#rpms[@]}" -gt 0 ] || { echo "no rpms in $rpmdir - build first"; exit 1; }

for r in "${rpms[@]}"; do
	echo "################################################################"
	echo "### $(basename "$r")"
	echo
	echo "# rpm -qpi (identity)"
	rpm -qpi "$r"
	echo
	echo "# rpm -qpl (contents)"
	rpm -qpl "$r"
	echo
	echo "# rpm -qp --requires"
	rpm -qp --requires "$r"
	echo
	echo "# rpm -qp --provides"
	rpm -qp --provides "$r"
	echo
	echo "# rpm -qp --scripts"
	rpm -qp --scripts "$r" || echo "(none)"
	echo
	echo "# modes / file caps"
	rpm -qp --qf '[%{FILEMODES:octal}  %{FILECAPS}  %{FILENAMES}\n]' "$r"
	echo
done

cat <<'EOF'
################################################################
# Extract an RPM for offline inspection (no install):
#
#   mkdir /tmp/x && cd /tmp/x
#   rpm2cpio /path/to/pkg.rpm | cpio -idmv          # or: rpm2archive - | tar xz
#
# Other useful non-installing queries:
#   rpm -qp --changelog pkg.rpm
#   rpm -qp --dump pkg.rpm
#   rpm -Kv pkg.rpm            # signature / digest check
EOF
