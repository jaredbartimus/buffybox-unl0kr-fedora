# COPR "make_srpm" entry point.
#
# COPR invokes:  make -f .copr/Makefile srpm outdir=<dir> spec=<path>
# in a chroot that has network access. We delegate to scripts/build-srpm.sh
# so the SRPM is produced identically here and in local/CI builds, including
# the sha256 verification of the pinned upstream archives.
#
# This deliberately does NOT track upstream HEAD: scripts/fetch-sources.sh
# downloads the exact tag/commit named in buffybox-unl0kr.spec and refuses to
# continue on a checksum mismatch.

srpm:
	dnf -y install rpm-build curl coreutils >/dev/null
	scripts/build-srpm.sh "$(outdir)"
