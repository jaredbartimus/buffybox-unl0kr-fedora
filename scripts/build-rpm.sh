#!/usr/bin/env bash
#
# Build the SRPM and binary RPMs inside an unprivileged Fedora 44 container.
#
# A fresh fedora:44 container is also the clean-room proof that the spec's
# BuildRequires are complete: nothing but "dnf builddep" is used to satisfy them.
#
# Usage: scripts/build-rpm.sh [ENGINE]
#   ENGINE   podman (default) or docker
#
# Results land in ./build/{SRPMS,RPMS} on the host.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
engine="${1:-podman}"
image="registry.fedoraproject.org/fedora:44"

command -v "$engine" >/dev/null || { echo "no such container engine: $engine" >&2; exit 1; }

mkdir -p "${repo_root}/build"

# The in-container build script. Kept inline so this file is self-contained.
# shellcheck disable=SC2016  # the single-quoted body runs in the container, not here
exec "$engine" run --rm \
	-v "${repo_root}:/pkg:z" \
	-w /pkg \
	"$image" \
	bash -euo pipefail -c '
	echo "::: dnf install base tooling"
	dnf -y --setopt=install_weak_deps=False install \
		rpm-build rpmdevtools rpmlint dnf-plugins-core meson gcc curl \
		glibc-langpack-en >/dev/null
	export LC_ALL=C.UTF-8

	echo "::: rpmdev-setuptree"
	export HOME=/root
	rpmdev-setuptree
	topdir=$(rpmbuild --eval %_topdir)

	echo "::: dnf builddep (proves BuildRequires completeness)"
	dnf -y builddep buffybox-unl0kr.spec >/dev/null

	echo "::: fetch + verify sources"
	scripts/fetch-sources.sh "${topdir}/SOURCES"
	cp -v buffybox-unl0kr.spec "${topdir}/SPECS/"
	cp -v ARCHITECTURE-SECURITY.md "${topdir}/SOURCES/"
	[ -d patches ] && cp patches/*.patch "${topdir}/SOURCES/"

	echo "::: rpmbuild -bs (SRPM)"
	rpmbuild -bs "${topdir}/SPECS/buffybox-unl0kr.spec"

	echo "::: rpmbuild --rebuild (binary RPMs from the SRPM)"
	rpmbuild --rebuild "${topdir}"/SRPMS/buffybox-unl0kr-*.src.rpm

	echo "::: collect results"
	rm -rf build/SRPMS build/RPMS
	mkdir -p build/SRPMS build/RPMS
	cp -v "${topdir}"/SRPMS/*.src.rpm build/SRPMS/
	find "${topdir}/RPMS" -name "*.rpm" -exec cp -v {} build/RPMS/ \;

	echo "::: rpmlint"
	rpmlint buffybox-unl0kr.spec || true
	rpmlint -r ci/rpmlintrc build/SRPMS/*.src.rpm build/RPMS/*.rpm || true

	echo "::: done - artifacts in ./build"
	ls -R build
	'
