# buffybox-unl0kr-fedora

Fedora RPM packaging for **Unl0kr**, the touchscreen-friendly disk unlocker,
built from the maintained **BuffyBox** source tree. Targets Fedora 44 x86_64
and automated COPR builds, on the way to a later Bazzite / ROG Ally X
integration phase.

> This repository packages *the Unl0kr subset* of BuffyBox. It is not, and does
> not claim to be, complete Fedora packaging of BuffyBox. See
> [Scope](#scope-and-package-names).

---

## 1. What BuffyBox / Unl0kr is

**Unl0kr** is a full-screen disk unlocker for the initramfs, built on
[LVGL](https://lvgl.io). It renders directly to the Linux framebuffer or via
DRM/KMS - no GPU acceleration, no compositor, no X/Wayland - and shows an
on-screen keyboard so a LUKS passphrase can be entered by **touchscreen, mouse
or physical keyboard**, with input devices discovered at runtime through
libinput. On completion it writes the passphrase to standard output and nothing
else; all diagnostics go to standard error. It is an
[osk-sdl](https://gitlab.com/postmarketOS/osk-sdl) successor and is the default
unlocker on postmarketOS.

Unl0kr no longer exists as a standalone project. It is one component of
**BuffyBox**, a small monorepo that also contains `buffyboard` (a framebuffer
on-screen keyboard for the console) and `f0rmz` (a forms UI). BuffyBox also
contains a native **systemd password agent** for Unl0kr.

* Canonical upstream: <https://gitlab.postmarketos.org/postmarketOS/buffybox>
* The older `gitlab.com/cherrypicker/unl0kr` and `github.com/droidian/unl0kr`
  trees are previous standalone generations and are **not** used here.

## 2. Why this packaging exists

Fedora and COPR have no current Unl0kr package. The historical
Bazzite / KyleGospo Unl0kr COPRs were built from the *old standalone* codebase
and are only of historical interest - do not treat them as trustworthy inputs.

This repo provides a clean, reproducible, review-before-publish packaging of
**current** BuffyBox so that Unl0kr can be built for Fedora 44 and, in a later
phase, wired into the Bazzite initramfs on an ASUS ROG Ally X.

## 3. Upstream source and reproducibility

| Input | Pin | Where |
|---|---|---|
| BuffyBox | tag **`3.6.0`**, commit `d0f52495f7f3afa8839eef4b19f43f4ca1243107` | GitLab tag archive |
| LVGL (bundled, static) | commit `85aa60d18b3d5e5588d7b247abf90198f07c8a63` = **v9.5.0** | GitHub commit archive |

* The **commit SHAs are the identity**. `sources.sha256` additionally records a
  sha256 for each archive as a tamper check. Auto-generated forge archives are
  content-immutable but not contractually byte-stable; if a sum ever drifts,
  verify the tree against the commit SHA before touching the file.
* We do **not** use the BuffyBox 3.6.0 *release asset* - it was published
  without the lvgl submodule (2 MB vs. the expected ~100 MB). We use the tag
  archive plus a separately pinned lvgl archive, the same shape postmarketOS
  pmaports uses.
* `%prep` never runs git, never fetches submodules, never touches the network.
* `scripts/fetch-sources.sh` is the only network step; it downloads with
  `curl --fail` and then `sha256sum -c sources.sha256`, failing closed.
* COPR is configured for a **fixed branch**, never "latest upstream HEAD"
  (see [§7](#7-building-via-copr)).

## 4. Supported Fedora versions

* **Fedora 44 x86_64** - the build/CI target, and the base of Bazzite Deck
  stable.

Other releases/arches are not tested. All build dependencies exist in Fedora 42+
so it will likely build there; only F44 is verified.

## 5. Scope and package names

```
Source RPM:  buffybox-unl0kr        (name makes the "Unl0kr subset" explicit)

Binary RPMs: unl0kr                 /usr/bin/unl0kr, /etc/unl0kr.conf, man pages
             unl0kr-agent           /usr/libexec/unl0kr-agent + systemd units
             unl0kr-debuginfo, unl0kr-agent-debuginfo, buffybox-unl0kr-debugsource
```

**Out of scope on purpose:** `buffyboard` and `f0rmz`. Upstream tags every
meson install target (`install_tag: 'unl0kr'` vs `'buffyboard'` / `'f0rmz'`);
the spec runs `meson install --tags unl0kr`, so those components are simply not
installed - nothing is deleted, and `%check` fails the build if a
`buffyboard`/`f0rmz` file ever leaks into the buildroot.

**Migration path.** The binary RPM names `unl0kr` and `unl0kr-agent` are exactly
what a future *complete* `buffybox` source package would produce. The SRPM name
is invisible to installed systems, so switching later to a full `buffybox` SRPM
is a drop-in replacement - no `Obsoletes`/`Provides` churn on the binary
packages, only the COPR package entry changes.

### Downstream patches

There is currently **one downstream patch** (`0001-unl0kr-agent-watch-request-files-only.patch`) carried in this repository.

It changes the `unl0kr-agent.path` unit to watch for actual `ask.*` password request files (`PathExistsGlob=/run/systemd/ask-password/ask.*`) instead of just checking if the directory is not empty (`DirectoryNotEmpty=/run/systemd/ask-password`). The original behavior triggered an activation crash-loop (hitting the systemd start-limit) when aborted requests left behind residual `sck.*` response sockets.

This patch is intended to be dropped once the fix is merged in a future upstream release.
If a future automated version bump pulls in the upstream fix, the RPM build will fail cleanly when `%autopatch` cannot apply. A maintainer must then remove the downstream patch and bump the spec.

The historical Unl0kr defects (minui.c compiled when disabled; passphrase printed with a trailing newline) and the Debian 32-bit uinput patch are all fixed upstream in 3.6.0.

## 6. Building locally

Needs a Fedora 44 environment. If your host is not Fedora, use a container
(rootless podman shown; docker works too):

```bash
# one-shot: SRPM + RPMs + rpmlint, results in ./build/
scripts/build-rpm.sh podman
```

Step by step, inside `registry.fedoraproject.org/fedora:44`:

```bash
dnf -y install rpm-build rpmdevtools dnf-plugins-core meson gcc curl
rpmdev-setuptree
scripts/fetch-sources.sh "$(rpmbuild --eval %_topdir)/SOURCES"
cp ARCHITECTURE-SECURITY.md "$(rpmbuild --eval %_topdir)/SOURCES/"
cp dracut/module-setup.sh "$(rpmbuild --eval %_topdir)/SOURCES/"
cp patches/*.patch "$(rpmbuild --eval %_topdir)/SOURCES/"
cp buffybox-unl0kr.spec "$(rpmbuild --eval %_topdir)/SPECS/"
dnf -y builddep buffybox-unl0kr.spec
rpmbuild -ba "$(rpmbuild --eval %_topdir)/SPECS/buffybox-unl0kr.spec"
```

Clean-chroot build with mock (maintainer sanity check, not run in CI):

```bash
scripts/mock-build.sh fedora-44-x86_64
```

### Inspecting the RPMs without installing

```bash
scripts/inspect-rpms.sh build/RPMS        # full query battery for every rpm
```

which runs, per package:

```bash
rpm -qpl   pkg.rpm      # file list
rpm -qpi   pkg.rpm      # identity: version, license, summary, size
rpm -qp --requires  pkg.rpm
rpm -qp --provides  pkg.rpm
rpm -qp --scripts   pkg.rpm      # scriptlets
rpm -qp --qf '[%{FILEMODES:octal} %{FILECAPS} %{FILENAMES}\n]' pkg.rpm
```

Extract an RPM to look inside it, still without installing:

```bash
mkdir /tmp/x && cd /tmp/x
rpm2cpio /path/to/pkg.rpm | cpio -idmv     # or: rpm2archive - | tar xz
```

`tests/validate-rpms.sh build/RPMS` runs the automated version of the above:
exact package set, file lists diffed against `tests/expected-files/`, expected
sonames, no setuid/setgid/caps, scriptlets limited to the systemd helpers, the
baked-in `/usr/bin/unl0kr` path, and `systemd-analyze verify` on both units.

## 7. Building via COPR

Model: this git repo -> COPR **SCM package** (`make_srpm`) -> Fedora 44 x86_64.
`.copr/Makefile` calls `scripts/build-srpm.sh`, so the SRPM is produced
identically in COPR and locally, **including the sha256 verification** of the
pinned archives.

```bash
# one-time project + package setup
copr-cli create-project --chroot fedora-44-x86_64 <you>/buffybox-unl0kr-fedora

copr-cli add-package-scm \
    --name buffybox-unl0kr \
    --clone-url https://github.com/<you>/buffybox-unl0kr-fedora.git \
    --commit main \
    --subdir . \
    --spec buffybox-unl0kr.spec \
    --type git \
    --method make_srpm \
    <you>/buffybox-unl0kr-fedora

# build it
copr-cli build-package --name buffybox-unl0kr <you>/buffybox-unl0kr-fedora

# rebuild after merging packaging changes: identical command
copr-cli build-package --name buffybox-unl0kr <you>/buffybox-unl0kr-fedora
```

`--commit main` tracks the reviewed packaging branch. COPR never chases
upstream: the version comes from the spec, and a bump only lands via the PR flow
below. Optionally enable COPR's "auto-rebuild on git push" webhook - it still
only builds whatever `main` says.

## 8. How upstream updates are handled

```
new BuffyBox release (GitLab releases API, never HEAD)
        -> .github/workflows/upstream-check.yml (weekly / manual)
        -> scripts/check-upstream.py --write
             updates Version, %global buffybox_commit,
             %global lvgl_commit + lvgl_version, sources.sha256
             (downloads + hashes both archives) and the section 3
             pin table; prepends a %changelog entry
             - takes the release commit from the releases API and
               verifies it against the tag archive's pax_global_header
               before writing anything
             - re-resolves the lvgl submodule commit AT THE NEW TAG,
               because a BuffyBox release can move it
        -> opens a pull request (never a direct push, never auto-merge)
        -> CI (build.yml) builds and validates the PR
        -> a human reviews the diff + green run, merges
        -> COPR builds main
```

No tokens are stored in the repo; the workflow uses the built-in
`GITHUB_TOKEN`. Opening PRs from Actions requires the repo setting
*Settings -> Actions -> General -> "Allow GitHub Actions to create and approve
pull requests"* (or a fine-grained PAT in `secrets` if you prefer).

Dry run locally:

```bash
python3 scripts/check-upstream.py          # reports, exits 10 if newer
```

## 9. Security model

Full detail in [`ARCHITECTURE-SECURITY.md`](ARCHITECTURE-SECURITY.md). In brief:

* **Deterministic sources.** Two inputs, pinned by commit, sha256-checked at
  build time, failing closed. No curl-pipe-shell, no unpinned clones, no
  submodule fetches during `%build`.
* **No secret handling in packaging.** Unl0kr writes the passphrase only to
  stdout (one `printf`, no logging path). The agent zeroes its passphrase
  buffer before `free()` and replies over a root-only `AF_UNIX` datagram
  socket.
* **Scriptlets** are only `%systemd_post` / `%systemd_preun` / `%systemd_postun`
  on `unl0kr-agent.path` (the `.service` has no `[Install]`). No `%pre`, no
  filesystem mutation, no daemon restart.
* **Privilege.** `unl0kr-agent.service` runs as **root** - required to read
  `/run/systemd/ask-password/ask.*` (mode 0600) and to open DRM/input devices.
  No setuid, no file capabilities, no sandbox directives (a UI that needs DRM
  master before real-root is mounted). Documented, not hidden.
* **Not enabled by default.** The package ships no systemd preset, so
  `%systemd_post` leaves `unl0kr-agent.path` disabled on a stock Fedora
  install; enabling it is an explicit admin (or downstream preset-policy)
  action because it changes boot-time passphrase prompting.
* **Coexistence.** The password-agent protocol is multi-agent - first valid
  answer wins - and upstream sets no `Conflicts=`. Stock agents do **not** need
  masking; the only real contention is who draws on the screen. Physical-
  keyboard fallback is preserved inside Unl0kr itself.

## 10. Tested hardware context

The intended deployment is **Bazzite Deck stable (Fedora 44 base) on an ASUS
ROG Ally X**. An older standalone Unl0kr build was hand-tested on that device:
AMDGPU DRM on `/dev/dri/card1`, panel `eDP-1` at 1920x1080, touchscreen
`NVTK0603:00 0603:F200` on `/dev/input/event5` via libinput (`hid_multitouch` /
`i2c_hid` / `i2c_hid_acpi` / `i2c_designware`), with touch typing and passphrase
submission confirmed. The relevant touch kmods are already in the Bazzite
initramfs. No Ally-specific kernel driver packaging is therefore planned.

The packaged **BuffyBox 3.6.0 RPMs have now been verified on this hardware** (DRM rendering, touchscreen typing, and password-agent response) during a live graphical session.

However, **actual initramfs/boot-time DRM handoff and LUKS unlock remain untested**. See
[`BAZZITE-DRACUT-TODO.md`](BAZZITE-DRACUT-TODO.md).

## 11. Not implemented yet

**Bazzite initramfs / dracut deployment.** This repo builds RPMs; it does not
create a dracut module, touch `/etc/crypttab`, regenerate any initramfs, call
`systemd-cryptenroll`, change LUKS keyslots, alter GRUB/Secure Boot/TPM, mask
any stock password agent, or install anything onto a Bazzite host. The full
open-items list - starting with the `ConditionPathExists=!/run/plymouth/pid`
issue that stops the agent starting under plymouth - is in
[`BAZZITE-DRACUT-TODO.md`](BAZZITE-DRACUT-TODO.md).

---

## Repository layout

```
buffybox-unl0kr.spec        the spec (single source of truth for the pins)
sources.sha256              pinned archive checksums, enforced by fetch-sources.sh
ARCHITECTURE-SECURITY.md    agent protocol, privilege, passphrase-path notes
BAZZITE-DRACUT-TODO.md      the deliberately-deferred initramfs phase
.copr/Makefile              COPR make_srpm entry point
scripts/
  fetch-sources.sh          download + verify the two pinned archives
  build-srpm.sh             fetch + rpmbuild -bs   (also used by .copr/Makefile)
  build-rpm.sh              full container build -> ./build/
  mock-build.sh             clean-chroot build (maintainer, not CI)
  inspect-rpms.sh           the rpm -qp... battery, human-readable
  check-upstream.py         release checker for the update workflow
tests/
  expected-files/*.txt      exact file manifests for unl0kr / unl0kr-agent
  validate-rpms.sh          automated post-build validation
.github/workflows/
  build.yml                 lint + SRPM + RPM + validate, in fedora:44
  upstream-check.yml         weekly release check -> PR
```

## License

The packaging in this repository is under the same license as the software it
packages, **GPL-3.0-or-later**. Unl0kr itself bundles LVGL (MIT) and font glyph
data derived from Open Sans (Apache-2.0) and Font Awesome 5 Free (OFL-1.1); the
`unl0kr` binary RPM's `License:` field reflects that combination.
