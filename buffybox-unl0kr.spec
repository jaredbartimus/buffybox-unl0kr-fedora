# This package builds ONLY the Unl0kr subset of the BuffyBox source tree
# (the disk unlocker and its systemd password agent). The buffyboard and
# f0rmz binaries that also live in the BuffyBox tree are intentionally out
# of scope for this packaging effort - see README.md.
#
# The source RPM is named "buffybox-unl0kr" to make that scoping explicit.
# The binary RPMs are named "unl0kr" and "unl0kr-agent" so that a future
# complete "buffybox" source package can produce them unchanged.

# Upstream pins. The commit SHAs are the reproducibility identity; the
# sha256 sums live in sources.sha256 and are checked by scripts/fetch-sources.sh.
%global buffybox_commit d0f52495f7f3afa8839eef4b19f43f4ca1243107
%global lvgl_commit     85aa60d18b3d5e5588d7b247abf90198f07c8a63
%global lvgl_version     9.5.0

Name:           buffybox-unl0kr
Version:        3.6.0
Release:        2%{?dist}
Summary:        Touchscreen disk unlocker for the initramfs (BuffyBox / Unl0kr)

# Project code (buffybox, squeek2lvgl): GPL-3.0-or-later
# Bundled LVGL (statically linked):     MIT
# Glyph bitmaps compiled into shared/fonts/font_32.c:
#   OpenSans .......... Apache-2.0
#   Font Awesome 5 Free  OFL-1.1
License:        GPL-3.0-or-later AND MIT AND Apache-2.0 AND OFL-1.1
URL:            https://gitlab.postmarketos.org/postmarketOS/buffybox

# Source0: immutable GitLab tag archive (NOT the release asset - the 3.6.0
#          release asset was published without the lvgl submodule).
# Source1: lvgl pinned by commit (== upstream v9.5.0 tag). Commit form, not
#          refs/tags, because the submodule records a commit and tags can move.
Source0:        https://gitlab.postmarketos.org/postmarketOS/buffybox/-/archive/%{version}/buffybox-%{version}.tar.gz
Source1:        https://github.com/lvgl/lvgl/archive/%{lvgl_commit}.tar.gz#/lvgl-%{lvgl_commit}.tar.gz
# Downstream documentation shipped in the unl0kr-agent package.
Source2:        ARCHITECTURE-SECURITY.md

Patch0:         patches/0001-unl0kr-agent-watch-request-files-only.patch

# Downstream patch: watch only for actual ask-password request files, avoiding
# a start-limit-hit crash loop when only residual response sockets remain.
# This patch is intended to be dropped once the fix is available in the packaged
# upstream revision. The historical Unl0kr defects and Debian patch are all
# upstream as of 3.6.0. See README.md and ARCHITECTURE-SECURITY.md.

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(inih)
BuildRequires:  pkgconfig(libinput)
BuildRequires:  pkgconfig(libudev)
BuildRequires:  pkgconfig(xkbcommon)
BuildRequires:  pkgconfig(libdrm)
BuildRequires:  pkgconfig(scdoc)
BuildRequires:  pkgconfig(systemd)
BuildRequires:  systemd-rpm-macros

%description
BuffyBox is the maintained lineage of Unl0kr, a lightweight full-screen
disk unlocker for the initramfs built on LVGL. It renders directly to the
Linux framebuffer or via DRM/KMS - no GPU acceleration or compositor
required - and drives an on-screen keyboard from touchscreens, mice and
physical keyboards discovered through libinput.

This source package builds the Unl0kr disk unlocker and its systemd
password agent. It does not build the buffyboard or f0rmz components that
also live in the BuffyBox tree.

%package -n unl0kr
Summary:        Touchscreen-friendly disk unlocker for the initramfs, based on LVGL
Provides:       bundled(lvgl) = %{lvgl_version}

%description -n unl0kr
Unl0kr is a full-screen disk unlocker for the initramfs. It renders to the
Linux framebuffer or through DRM/KMS and presents an on-screen keyboard so
a LUKS passphrase can be entered by touch, mouse or physical keyboard. On
completion the passphrase is written to standard output; all other output
goes to standard error.

This package contains the unl0kr binary, its configuration file and manual
pages. It does not enable anything on its own - integrating unl0kr into the
boot process is a separate, distribution-specific step.

%package -n unl0kr-agent
Summary:        Password agent that unlocks disks with unl0kr
License:        GPL-3.0-or-later
Requires:       unl0kr%{?_isa} = %{version}-%{release}
%{?systemd_requires}

%description -n unl0kr-agent
A systemd password agent that answers passphrase requests from
/run/systemd/ask-password by launching unl0kr. It ships no systemd preset, so
on a stock Fedora install unl0kr-agent.path is not enabled; enabling it
changes how disk-encryption passphrases are requested at boot and is an
administrator (or downstream preset-policy) decision.

The agent runs as root (it must read root-owned request files and open
input and DRM devices) and coexists with the stock systemd password
agents - the first agent to answer a given request wins. See
ARCHITECTURE-SECURITY.md in this package's documentation directory.

%prep
%setup -q -n buffybox-%{version} -a 1
%autopatch -p1
# BuffyBox vendors lvgl as a git submodule; the tag archive ships an empty
# lvgl/ directory. Replace it with the pinned lvgl tree (Source1).
rm -rf lvgl
mv lvgl-%{lvgl_commit} lvgl
# Sanity: the file meson executes at configure time must stay executable.
test -x find-lvgl-sources.sh
# Stage downstream docs into the build tree so the package can ship them.
cp -p %{SOURCE2} .

%build
# Do NOT override b_ndebug. Upstream sets b_ndebug=if-release; combined with
# Fedora's --buildtype=plain this compiles out asserts, which is exactly how
# the postmarketOS/Alpine reference package builds unl0kr-agent. Forcing
# asserts back on would let an over-strict invariant abort() the password
# agent during boot. See ARCHITECTURE-SECURITY.md.
%meson -Dsystemd=true -Dman=true
%meson_build

%install
# Install only the targets upstream tags as 'unl0kr' (binary, config, agent,
# both units, the two unl0kr man pages). buffyboard/f0rmz targets carry
# different install_tag values and are skipped - nothing is deleted here.
%meson_install --tags unl0kr

# Home for administrator drop-ins (unl0kr reads /etc/unl0kr.conf.d/*.conf).
# Upstream ships no vendor config in this directory.
install -d -m 0755 %{buildroot}%{_sysconfdir}/unl0kr.conf.d

%check
# Two invariants, checked early so a bad upstream change fails the build:
#   1. every file we expect from install_tag 'unl0kr' is present
#   2. nothing from the buffyboard / f0rmz targets leaked into the buildroot
# (/usr/{lib,src}/debug is generated by find-debuginfo and is not our concern)
cd %{buildroot}
fail=0
for f in \
    .%{_bindir}/unl0kr \
    .%{_sysconfdir}/unl0kr.conf \
    .%{_sysconfdir}/unl0kr.conf.d \
    .%{_libexecdir}/unl0kr-agent \
    .%{_unitdir}/unl0kr-agent.path \
    .%{_unitdir}/unl0kr-agent.service; do
    if [ ! -e "$f" ]; then echo "MISSING: $f" >&2; fail=1; fi
done
for m in .%{_mandir}/man1/unl0kr.1 .%{_mandir}/man5/unl0kr.conf.5; do
    if ! ls "$m"* >/dev/null 2>&1; then echo "MISSING: $m*" >&2; fail=1; fi
done
leaked=$(find . -path ./usr/lib/debug -prune -o -path ./usr/src/debug -prune -o \
    \( -iname '*buffyboard*' -o -iname '*f0rmz*' \) -print)
if [ -n "$leaked" ]; then echo "SCOPE LEAK:" >&2; echo "$leaked" >&2; fail=1; fi
test "$fail" -eq 0

%files -n unl0kr
%license COPYING
%doc unl0kr/README.md CHANGELOG.md
%{_bindir}/unl0kr
%config(noreplace) %{_sysconfdir}/unl0kr.conf
%dir %{_sysconfdir}/unl0kr.conf.d
%{_mandir}/man1/unl0kr.1*
%{_mandir}/man5/unl0kr.conf.5*

%files -n unl0kr-agent
%license COPYING
%doc ARCHITECTURE-SECURITY.md
%{_libexecdir}/unl0kr-agent
%{_unitdir}/unl0kr-agent.path
%{_unitdir}/unl0kr-agent.service

%post -n unl0kr-agent
# .path is the enable target; unl0kr-agent.service has no [Install] section.
%systemd_post unl0kr-agent.path

%preun -n unl0kr-agent
%systemd_preun unl0kr-agent.path

%postun -n unl0kr-agent
# No _with_restart: restarting a password dispatcher mid-request is wrong.
%systemd_postun unl0kr-agent.path

%changelog
* Sun Sep 06 2026 Jared <jared555@gmail.com> - 3.6.0-2
- Add downstream patch to watch only ask-password request files
- Fixes start-limit-hit on unl0kr-agent when response sockets are abandoned

* Sun Sep 06 2026 Jared <jared555@gmail.com> - 3.6.0-1
- Initial Fedora packaging of the Unl0kr subset of BuffyBox 3.6.0
- lvgl bundled at 85aa60d18b3d5e5588d7b247abf90198f07c8a63 (upstream v9.5.0)
- No downstream patches
