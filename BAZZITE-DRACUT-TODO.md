# Not implemented yet: Bazzite initramfs / dracut integration

This repository packages Unl0kr into Fedora RPMs. It does **not** wire Unl0kr
into the boot process. That is a deliberately separate phase because it touches
the initramfs and the encrypted-root unlock path on a real machine.

Nothing in this repo modifies `/etc/crypttab`, LUKS keyslots, the bootloader,
Secure Boot, the TPM, `rpm-ostree` initramfs state, or the running host.

The hardware target for the later phase is an **ASUS ROG Ally X running Bazzite
(Fedora 44 base)**. An older standalone Unl0kr build was hand-tested on that
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

Touchscreen typing and passphrase submission were verified on that device with
the older build.

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

### 2. There is no dracut module - it has to be written

Upstream ships integration for **other** init systems only:

* Debian `debian/initramfs/{hooks,scripts}` (initramfs-tools);
* postmarketOS mkinitfs triggers + `main/unl0kr/unl0kr.files`.

Fedora/Bazzite needs a `dracut` module (`/usr/lib/dracut/modules.d/XXunl0kr/`)
written from scratch:

* `module-setup.sh` with `install()` / `installkernel()` / `depends()`;
* pull in the `unl0kr` binary and `/etc/unl0kr.conf`;
* pull in the pieces Unl0kr needs at runtime that **no package dependency
  currently drags in**:
  * libinput quirks: `/usr/share/libinput/*.quirks`,
  * libinput udev helpers + rules:
    `/usr/lib/udev/libinput-*`, `/usr/lib/udev/rules.d/*-libinput-*.rules`,
  * XKB data: `/usr/share/X11/xkb` (or the compiled keymap),
  * `hid-multitouch` / `i2c-hid*` kmods (already present on the Ally X image,
    but `installkernel()` should request them for portability);
* decide agent vs. keyscript:
  * **agent**: install `unl0kr-agent` + the two units into the initramfs and
    resolve item 1;
  * **keyscript**: a `crypttab` `keyscript=` wrapper that runs
    `unl0kr -n` and feeds stdout to cryptsetup (mirrors what Debian's
    `unl0kr-keyscript` / the old osk-sdl integration did).

Ship it as a **separate** `unl0kr-dracut` subpackage or a separate repo; do not
fold it into `unl0kr` until it is proven on hardware.

### 3. rpm-ostree / ostree layering

Bazzite is image-based. Work out how the dracut module and any
`/etc` config survive:

* `rpm-ostree install unl0kr unl0kr-dracut` layering vs. baking into a custom
  image;
* whether `rpm-ostree initramfs --enable` (or a `/etc/dracut.conf.d` drop-in)
  is needed for the module to be picked up, and that this is the user's
  decision, made on their machine, not here.

### 4. Coexistence with the stock console agent, on hardware

`ARCHITECTURE-SECURITY.md` §3.3 argues the password-agent protocol lets Unl0kr
and `systemd-ask-password-console` coexist (first valid answer wins) and that
the only real conflict is who owns the display. That needs a real test:

* Unl0kr taking DRM master on `/dev/dri/card1` while the console agent is also
  active;
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

* DRM handoff / modeset on the Ally X panel from within the initramfs;
* touch input latency and the on-screen keyboard at 1920x1080;
* that the passphrase reaches cryptsetup as exactly the typed bytes
  (`unl0kr -n` + agent `+`-prefixed datagram - verified in code, not on metal);
* power/suspend behaviour if the unlock prompt sits idle.
