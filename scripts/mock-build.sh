#!/usr/bin/env bash
#
# Maintainer-only: clean-chroot build with mock, as the belt-and-braces check
# that the spec's BuildRequires are complete and the package builds from a
# pristine root. NOT part of CI (mock wants a privileged/allowed environment).
#
# Requires: mock, and either running as a member of the 'mock' group or via
# rootless podman with --privileged (see README "Local build").
#
# Usage: scripts/mock-build.sh [CHROOT]
#   CHROOT  default: fedora-44-x86_64

set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chroot="${1:-fedora-44-x86_64}"

command -v mock >/dev/null || { echo "mock not installed"; exit 1; }

srpmdir="${repo_root}/build/SRPMS"
"${repo_root}/scripts/build-srpm.sh" "$srpmdir"
srpm="$(find "$srpmdir" -name 'buffybox-unl0kr-*.src.rpm' -printf '%T@ %p\n' \
	| sort -rn | head -n1 | cut -d' ' -f2-)"

echo ">> mock -r ${chroot} ${srpm}"
mock -r "$chroot" --resultdir="${repo_root}/build/mock-${chroot}" "$srpm"

echo ">> results in build/mock-${chroot}"
ls -l "${repo_root}/build/mock-${chroot}"
