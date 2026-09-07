# Bazzite initramfs / dracut integration status

Integration with dracut must be validated to correctly unlock the root LUKS volume during the initial Fedora Atomic boot phase (the initramfs).

## 1. Initramfs graphical capability
[X] Bazzite stock initramfs contains the kernel modules already observed as required for the Ally X touchscreen/AMDGPU path.
[X] Synthetic Fedora 44 dracut image contains the packaged libinput and XKB user-space runtime assets.
[ ] Verify on the real Ally X initramfs that the NVTK0603 touchscreen enumerates and receives `ID_INPUT_TOUCHSCREEN=1`.

## 2. Dracut module: composition implemented, hardware integration not yet validated

The hardware target for the later phase is an **ASUS ROG Ally X running Bazzite
(Fedora 44 base)**. The packaged BuffyBox 3.6.0 RPMs have been tested on that
device and the following were confirmed working, which is why no Ally-specific
kernel driver packaging is planned:

| Thing | Value |
|---|---|
| GPU / DRM | AMDGPU, `/dev/dri/card1` |
| Panel | `eDP-1`, 1920x1080 |
| Touchscreen | `NVTK0603:00 0603:F200`, `/dev/input/event5` |
| Touch stack | `hid_multitouch`, `i2c_hid`, `i2c_hid_acpi`, `i2c_designware` |
| Already in Bazzite initramfs | `hid-multitouch.ko`, `i2c-hid.ko`, `i2c-hid-acpi.ko` |
| Built into Bazzite kernel | `i2c_designware_platform`, `i2c_designware_core`, `evdev` |

During a live graphical session on this hardware, the packaged `/usr/bin/unl0kr` rendered successfully via DRM/KMS, touchscreen typing and submission worked, `unl0kr -n` returned exactly the entered bytes with no trailing newline, and the packaged `/usr/libexec/unl0kr-agent` successfully answered a synthetic `systemd-ask-password` request. `autohide=false` is needed for immediate OSK visibility on this device, and `haptic_feedback=false` is needed to avoid a continuous vibration issue. Normal systemd-service invocation under the running desktop did not visibly take over the display.

A downstream patch (`0001-unl0kr-agent-watch-request-files-only.patch`) has been added to fix a path-unit start-limit crash loop. When password requests are timed out or cancelled, residual `sck.*` response sockets remain. The patch updates `unl0kr-agent.path` to use `PathExistsGlob` on `ask.*` files rather than `DirectoryNotEmpty`, preventing a retrigger loop on the leftover sockets.

---

## Open items, roughly in priority order

### 1. The plymouth condition (blocker)

Both `unl0kr-agent.path` and `unl0kr-agent.service` ship with:

```
ConditionPathExists=!/run/plymouth/pid
```

Bazzite boots with plymouth active, so **the agent will not start** on a stock
Bazzite boot. This is upstream deliberately yielding the screen to plymouth,
not something this packaging should paper over by masking other units.

Options to evaluate in the next phase:

* a systemd drop-in that drops the condition, accepting that Unl0kr and
  plymouth then race for the framebuffer/DRM master;
* switching the relevant boot to `plymouth.enable=0` (or a plymouth-less
  dracut profile) so the condition passes naturally;
* raising it upstream - e.g. a build/config switch to target
  "no plymouth in this initramfs" deployments.

### 2. Dracut module: composition implemented, hardware integration not yet validated

Upstream ships integration for **other** init systems only:

* Debian `debian/initramfs/{hooks,scripts}` (initramfs-tools);
* postmarketOS mkinitfs triggers + `main/unl0kr/unl0kr.files`.

Fedora/Bazzite needs a `dracut` module (`/usr/lib/dracut/modules.d/XXunl0kr/`)
written from scratch:

* `module-setup.sh` with `install()` / `depends()`;
* pull in the `unl0kr` binary and `/etc/unl0kr.conf`;
* pull in the pieces Unl0kr needs at runtime:
  * libinput quirks: `/usr/share/libinput/*.quirks`,
  * libinput udev helpers + rules:
    `/usr/lib/udev/libinput-*`, `/usr/lib/udev/rules.d/*-libinput-*.rules`,
  * XKB data: `/usr/share/X11/xkb` (or the compiled keymap).
* agent units: install `unl0kr-agent` + the two units into the initramfs and
  resolve item 1.

The module is strictly opt-in: installing the RPM does not add the module to an initramfs or regenerate the host initramfs. When the user explicitly includes `55unl0kr` in an initramfs build, the module enables `unl0kr-agent.path` inside that generated image.

### 3. rpm-ostree / ostree layering

Bazzite is image-based. Work out how the dracut module and any
`/etc` config survive:

* `rpm-ostree install unl0kr unl0kr-dracut` layering vs. baking into a custom
  image;
* whether `rpm-ostree initramfs --enable` (or a `/etc/dracut.conf.d` drop-in)
  is needed for the module to be picked up, and that this is the user's
  decision, made on their machine, not here.

#### Troubleshooting: Stale rpm-ostree metadata

On Bazzite, `dnf repoquery` may see a newer COPR build while `rpm-ostree` continues resolving an older layered RPM because its own `rpm-md` cache is stale.

If `rpm-ostree` repeatedly selects an older version than expected (for example, if DNF5 sees `unl0kr-3.6.0-2.fc44` but `rpm-ostree` selects `3.6.0-1`), force a metadata refresh with this recovery sequence:

```bash
sudo rpm-ostree cleanup -m
sudo rpm-ostree reload
sudo rpm-ostree refresh-md
```

Then verify the package selection before making changes:

```bash
sudo rpm-ostree install --dry-run <package>
```

*(In one reproduced instance, before cleanup, `rpm-ostree` showed COPR metadata generated at `2026-09-07T03:04:19Z` with 7 solvables. After the cleanup/refresh, it showed `2026-09-07T05:26:25Z` with 14 solvables, and the dry run correctly selected both `unl0kr-3.6.0-2.fc44.x86_64` and `unl0kr-agent-3.6.0-2.fc44.x86_64`.)*

### 4. Coexistence with the stock console agent, on hardware

`ARCHITECTURE-SECURITY.md` §3.3 argues the password-agent protocol lets Unl0kr
and `systemd-ask-password-console` coexist (first valid answer wins) and that
the only real conflict is who owns the display. That needs a real test:

* stock-agent/display coexistence in initramfs;
* confirming a physical keyboard still types into Unl0kr (libinput + XKB path);
* confirming `Ctrl+Alt+Fn` / fallback to the plain console prompt still works
  if Unl0kr is killed.

### 5. Report the upstream 3.6.0 tarball regression

The BuffyBox 3.6.0 GitLab *release asset*
(`.../uploads/c09c9c67.../buffybox-3.6.0.tar.gz`) was published **without the
lvgl submodule** (2 MB; 3.5.1's equivalent is 103 MB). This packaging sidesteps
it by using the tag archive + a separately pinned lvgl tarball, but Debian's
`watch` file points at that asset and will break. Worth a note to upstream.

### 6. Things that still need hardware to verify

* actual initramfs DRM handoff;
* Plymouth interaction at boot;
* runtime completeness of the dracut payload on the Ally X;
* end-to-end cryptsetup/LUKS root unlock;
* stock-agent/display coexistence in initramfs;
* physical keyboard fallback during actual early boot;
* power/suspend behavior while waiting at initramfs prompt.
