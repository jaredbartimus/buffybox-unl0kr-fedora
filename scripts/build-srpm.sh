#!/usr/bin/env bash
#
# Produce a source RPM in a self-contained way: fetch + verify the pinned
# upstream archives, then rpmbuild -bs. Used both locally and by
# .copr/Makefile (COPR's make_srpm method).
#
# Usage: scripts/build-srpm.sh [OUTDIR]
#   OUTDIR  where the .src.rpm should land (default: ./build/SRPMS)

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
spec="${repo_root}/buffybox-unl0kr.spec"
outdir="${1:-${repo_root}/build/SRPMS}"

command -v rpmbuild >/dev/null || { echo "rpmbuild not found (need rpm-build)"; exit 1; }

topdir="$(mktemp -d)"
trap 'rm -rf "$topdir"' EXIT
mkdir -p "$topdir"/{SOURCES,SPECS,SRPMS}

# Pinned tarballs + checksum verification (fails closed).
"${repo_root}/scripts/fetch-sources.sh" "${topdir}/SOURCES"

# Non-tarball Source files referenced by the spec.
cp "${repo_root}/ARCHITECTURE-SECURITY.md" "${topdir}/SOURCES/"
cp "$spec" "${topdir}/SPECS/"

rpmbuild -bs \
	--define "_topdir ${topdir}" \
	--define "_sourcedir ${topdir}/SOURCES" \
	--define "_srcrpmdir ${topdir}/SRPMS" \
	"${topdir}/SPECS/$(basename "$spec")"

mkdir -p "$outdir"
cp -v "${topdir}"/SRPMS/*.src.rpm "$outdir/"
