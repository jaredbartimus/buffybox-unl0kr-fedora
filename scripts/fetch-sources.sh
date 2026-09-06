#!/usr/bin/env bash
#
# Download the pinned upstream source archives and verify them against
# sources.sha256. Fails closed on any mismatch.
#
# Usage: scripts/fetch-sources.sh [OUTDIR]
#
#   OUTDIR  directory to place archives in (default: current directory).
#           Typically the rpmbuild SOURCES directory.
#
# The spec file is the single source of truth for the version and the pinned
# lvgl commit; this script parses it so the two can never drift.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
spec="${repo_root}/buffybox-unl0kr.spec"
checksums="${repo_root}/sources.sha256"
outdir="${1:-$PWD}"

die() { printf 'fetch-sources: %s\n' "$*" >&2; exit 1; }

[ -f "$spec" ]      || die "spec not found: $spec"
[ -f "$checksums" ] || die "checksums not found: $checksums"
mkdir -p "$outdir"

# --- parse pins out of the spec ------------------------------------------------
spec_get_global() {
	# %global <name> <value>
	sed -n "s/^%global[[:space:]]\+$1[[:space:]]\+\([^[:space:]]\+\).*/\1/p" "$spec" | head -n1
}
spec_get_tag() {
	# Tag:  value   (e.g. Version)
	sed -n "s/^$1:[[:space:]]*\([^[:space:]]\+\).*/\1/p" "$spec" | head -n1
}

version="$(spec_get_tag Version)"
lvgl_commit="$(spec_get_global lvgl_commit)"

[ -n "$version" ]     || die "could not read Version from spec"
[ -n "$lvgl_commit" ] || die "could not read %global lvgl_commit from spec"

buffybox_tar="buffybox-${version}.tar.gz"
lvgl_tar="lvgl-${lvgl_commit}.tar.gz"

buffybox_url="https://gitlab.postmarketos.org/postmarketOS/buffybox/-/archive/${version}/buffybox-${version}.tar.gz"
lvgl_url="https://github.com/lvgl/lvgl/archive/${lvgl_commit}.tar.gz"

# --- download (skip if already present and correct) --------------------------
fetch() {
	local url="$1" dest="$2"
	if [ -f "$dest" ]; then
		printf 'fetch-sources: %s already present, skipping download\n' "$(basename "$dest")"
		return 0
	fi
	printf 'fetch-sources: downloading %s\n' "$url"
	# --fail: no partial HTML error pages; -L: follow redirects
	curl --fail --location --show-error --silent \
	     --retry 3 --retry-delay 2 --max-time 600 \
	     --output "${dest}.part" "$url"
	mv "${dest}.part" "$dest"
}

fetch "$buffybox_url" "${outdir}/${buffybox_tar}"
fetch "$lvgl_url"     "${outdir}/${lvgl_tar}"

# --- verify ------------------------------------------------------------------
printf 'fetch-sources: verifying checksums\n'
( cd "$outdir" && sha256sum -c "$checksums" ) || die "checksum verification FAILED"

printf 'fetch-sources: OK - %s\n' "$buffybox_tar $lvgl_tar in $outdir"
