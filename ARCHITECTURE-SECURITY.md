# Unl0kr on Fedora — architecture & security notes

Short companion to the packaging. Everything here was checked by direct
inspection of the BuffyBox 3.6.0 source tree (commit
`d0f52495f7f3afa8839eef4b19f43f4ca1243107`), not assumed. These notes record
the revision that was **audited**; they are not regenerated on an upstream
bump. For the revision actually packaged right now, read `%global
buffybox_commit` / `%global lvgl_commit` in `buffybox-unl0kr.spec` and
`sources.sha256` - not this file.

---

## 1. What gets installed

| File | Package | Owner / mode | Purpose |
|---|---|---|---|
| `/usr/bin/unl0kr` | `unl0kr` | root:root 0755 | the unlocker UI; prints the passphrase to stdout |
| `/etc/unl0kr.conf` | `unl0kr` | root:root 0644, `%config(noreplace)` | theme / backend / keyboard config |
| `/etc/unl0kr.conf.d/` | `unl0kr` | root:root 0755 (dir only) | admin drop-ins, `*.conf`, merged alphabetically |
| `/usr/share/man/man{1,5}/unl0kr*` | `unl0kr` | root:root 0644 | manual pages |
| `/usr/libexec/unl0kr-agent` | `unl0kr-agent` | root:root 0755 | systemd password agent |
| `/usr/lib/systemd/system/unl0kr-agent.path` | `unl0kr-agent` | root:root 0644 | enable target for the agent |
| `/usr/lib/systemd/system/unl0kr-agent.service` | `unl0kr-agent` | root:root 0644 | oneshot that runs the agent |

No setuid or setgid bits. No file capabilities. No sysusers or tmpfiles
fragments. No udev rules. Nothing is enabled by installation.

Config search order (`unl0kr/main.c:416-419`):
`/usr/share/unl0kr/unl0kr.conf` → `/usr/share/unl0kr/unl0kr.conf.d/*` →
`/etc/unl0kr.conf` → `/etc/unl0kr.conf.d/*` → any `-C` override. This package
ships nothing under `/usr/share/unl0kr`, so `/etc` is authoritative.

---

## 2. The passphrase path

`unl0kr` itself only ever **writes the passphrase to stdout** and everything
else to stderr (`unl0kr/main.c:364-366`):

```c
static void print_password_and_exit(lv_obj_t *textarea) {
    /* Print the password to STDOUT */
    printf(cli_opts.newline ? "%s\n" : "%s", lv_textarea_get_text(textarea));
    ...
```

`-n` sets `cli_opts.newline = false` (`unl0kr/command_line.c:125`).

There is **no passphrase logging anywhere** — no debug branch, no verbose
branch, no file. The only sink is that one `printf`.

### 2.1 The historical trailing-newline defect is fixed upstream

An older standalone Unl0kr always did `printf("%s\n", ...)`, appending a
newline that became part of the LUKS key. In BuffyBox 3.6.0 the newline is
opt-out via `-n`, and **the agent always passes `-n`**
(`unl0kr/unl0kr-agent.c:431`, `argv[1] = "-n"`), so on the agent path the
passphrase is delivered as exactly the entered bytes. No downstream patch is
required. If you drive `unl0kr` by hand for a keyscript, pass `-n` yourself.

### 2.2 The historical minui build defect is fixed upstream

The old `find-lvgl-sources.sh` compiled `lv_drivers/display/minui.c`
unconditionally. BuffyBox 3.6.0 uses LVGL 9, vendors it at `lvgl/`, and
`find-lvgl-sources.sh` only globs `lvgl/src/**/*.c`. There is no `lv_drivers`
tree and no `minui.c` anywhere in the source. No downstream patch is required.

### 2.3 Asserts are compiled out — deliberately

Upstream sets `b_ndebug=if-release` in `meson.build`. With Fedora's
`%meson` (`--buildtype=plain`) that defines `NDEBUG`, so `assert()` calls are
removed — identical to how the postmarketOS/Alpine package builds. The spec
does **not** override this.

One consequence worth recording: `unl0kr/unl0kr-agent.c:245` puts a
side-effecting call inside an assert:

```c
assert(read(fd_inotify, buffer, buffer_size) == -1 && errno == EAGAIN); // no more events
```

With `NDEBUG` that `read()` does not happen. It is a defensive drain of the
inotify fd after the watched `ask.*` file is deleted. It is benign to skip
here: the watch is single-file with `IN_DELETE_SELF`, the kernel auto-removes
it and delivers `IN_IGNORED` (so there is nothing left to read), and the next
loop iteration calls `inotify_add_watch()` again, which re-arms the
edge-triggered epoll registration. Forcing asserts back on would instead let
an over-strict invariant — e.g. the exact-size check on line 236 — call
`abort()` inside the boot-time password agent, which is a worse failure than
the thing being checked. This is an upstream style question, not a packaging
bug, and it is left exactly as upstream and Alpine ship it.

### 2.4 In-memory handling

The agent zeroes its passphrase buffer before freeing
(`unl0kr/unl0kr-agent.c:84-91`, `erase_and_free`) and passes the child's
stdout straight into the reply. The buffer is a normal heap allocation — not
`mlock`ed, not from a secure allocator. `unl0kr` runs before swap is
typically active; still, this is the same exposure every stock password agent
has, and is noted rather than "fixed" here.

---

## 3. The systemd password agent

`unl0kr-agent` implements the documented
[systemd password agent protocol](https://systemd.io/PASSWORD_AGENTS/):

1. Scan `/run/systemd/ask-password/` for `ask.*` files
   (`unl0kr/unl0kr-agent.c:177`, `find_request`).
2. Parse the `[Ask]` INI (`Socket`, `Message`, `PID`, `NotAfter`, `Echo`,
   `Silent`, `AcceptCached`) with inih (`ini_parser`, line 139).
3. If `PID` is set and dead → remove the stale file and move on. If `NotAfter`
   is in the past → wait for removal.
4. `fork()` + `execv("/usr/bin/unl0kr", {"unl0kr", "-n", ["-m", <message>]})`
   with the child's stdout on a pipe (`exec_unl0kr`, line 390). The
   `/usr/bin/unl0kr` path is baked in at compile time from meson's
   `bindir` (`-DUNL0KR_BINARY`).
5. While the child runs, watch the `ask.*` file with
   `inotify(IN_DELETE_SELF)` and an absolute POSIX timer for `NotAfter`. If
   the file vanishes (another agent answered) the child is `SIGTERM`ed, then
   `SIGKILL`ed after 5 s (`event_loop` + `sigalarm`).
6. On success, send `+<passphrase>` to the `Socket` as a single
   `AF_UNIX`/`SOCK_DGRAM` datagram (`send_password`, line 93). On timeout,
   send `-`. The `+`/`-` prefix is the protocol's accept/deny marker.
7. Zero and free the passphrase, then wait for the `ask.*` file to be removed
   before looking for the next request.

### 3.1 Privilege

`unl0kr-agent.service` has **no `User=`**, so the agent runs as **root**. That
is required and minimal:

* `/run/systemd/ask-password/ask.*` are `0600 root:root`.
* the reply socket under `/run/systemd/ask-password/` is likewise root-only.
* `unl0kr` (the child) must open `/dev/dri/card*` or `/dev/fb0` and
  `/dev/input/event*`.

There is no capability set that would be sufficient but smaller, because DRM
master and the ask-password directory both effectively require root in the
initramfs/early-boot context this is meant for. The service does no explicit
sandboxing (`ProtectSystem=` etc.) — appropriate for a UI that needs the DRM
device and runs before the real root is mounted, but noted here so a future
hardening pass has a starting point.

### 3.2 Unit wiring

`unl0kr-agent.path`:

```
[Unit]
ConditionPathExists=!/run/plymouth/pid
DefaultDependencies=no
After=plymouth-start.service
Before=paths.target cryptsetup.target
Conflicts=emergency.service
Before=emergency.service shutdown.target
[Path]
PathExistsGlob=/run/systemd/ask-password/ask.*
MakeDirectory=yes
[Install]
WantedBy=paths.target
```

`unl0kr-agent.service` is a plain oneshot (`ExecStart=/usr/libexec/unl0kr-agent`)
with the **same `ConditionPathExists=!/run/plymouth/pid`** and **no `[Install]`
section**. The `.path` unit is therefore the only thing you enable, and the
scriptlets act on `unl0kr-agent.path`.

This unit uses a downstream patch to replace `DirectoryNotEmpty=/run/systemd/ask-password` with `PathExistsGlob=/run/systemd/ask-password/ask.*`. The original `DirectoryNotEmpty` condition also matches residual `sck.*` reply sockets left behind by timed-out or cancelled requests. This causes repeated activation of the oneshot agent until the systemd start-limit is hit, because the path unit immediately triggers again when only sockets remain. `PathExistsGlob` watches only actual password requests.

### 3.3 Coexistence with the stock agents — no masking needed

* The protocol is explicitly multi-agent. systemd writes one `ask.*` file and
  accepts the **first** valid `+`/`-` datagram on the socket, then removes the
  file; every other agent sees the removal via inotify and stops. Racing is
  safe by design.
* Upstream declares **no `Conflicts=`** against `systemd-ask-password-console`
  / `-plymouth` / `-wall`. Nothing in the units masks them.
* The genuine clash is not protocol-level, it is the display: `unl0kr` takes
  DRM master (or the fbdev) while `systemd-ask-password-console` writes the
  prompt to `/dev/console`. They fight over the screen, not the answer.
* **Physical-keyboard fallback is preserved.** `unl0kr` discovers and reads
  hardware keyboards itself through libinput, with XKB layouts — a USB or
  built-in keyboard types into the same UI the touchscreen does. You do not
  need the console agent for that.

### 3.4 Enablement is a preset-policy decision

This package ships **no systemd preset**. `%systemd_post` applies the system's
preset policy on initial install only (`$1 == 1`), so an administrator's later
`systemctl enable` is preserved across upgrades. On a stock Fedora install
nothing presets `unl0kr-agent.path`, so it stays **inactive and disabled**
until an explicit `systemctl enable --now unl0kr-agent.path`, because enabling
it changes how boot-time passphrase prompts are served.

A derived distribution, or a local `/etc/systemd/system-preset/*.preset`
drop-in, can preset the unit *on* at install time. That is a deliberate
downstream choice, not something this package asserts either way - and it is
worth calling out here because the intended deployment target (Bazzite Deck, a
Fedora derivative; see README section 10) is exactly that kind of downstream.

---

## 4. Supply-chain properties of this package

* Two source inputs, both pinned by commit. The exact commits are `%global
  buffybox_commit` and `%global lvgl_commit` in `buffybox-unl0kr.spec`; their
  archive digests are in `sources.sha256`. Both files are updated together by
  `scripts/check-upstream.py`, which also verifies the buffybox commit against
  the tag archive's `pax_global_header` before writing.
* `scripts/fetch-sources.sh` downloads with `curl --fail` and then runs
  `sha256sum -c sources.sha256`, failing closed. It is the only network step,
  and it happens before `rpmbuild`.
* `%prep` does not run git, does not fetch submodules, does not touch the
  network. `--wrap-mode=nodownload` is implied by `%meson`; there are no
  meson subprojects anyway.
* No downstream patches, so there is no `patches/` directory to audit.
* Scriptlets are only the three `%systemd_*` macros, all on
  `unl0kr-agent.path`. No `%pre`, no filesystem mutation, no daemon restart.
* LVGL is statically linked into `unl0kr`; the RPM carries
  `Provides: bundled(lvgl) = 9.5.0` so a future LVGL CVE can find it.
  `unl0kr-agent` links only inih, dynamically.

---

## 5. Known gaps (tracked in BAZZITE-DRACUT-TODO.md)

1. `ConditionPathExists=!/run/plymouth/pid` on **both** agent units means that
   on a stock plymouth boot (Bazzite included) the agent does not start at
   all. This is upstream deliberately yielding to plymouth, not a masking
   problem, and it is the first thing the initramfs phase has to resolve.
2. No dracut module exists — upstream ships Debian initramfs-tools hooks and
   postmarketOS mkinitfs triggers only. A Fedora dracut module has to be
   written from scratch and is explicitly out of scope here.
3. The in-initramfs pieces `unl0kr` needs at runtime (libinput `.quirks`, XKB
   data, `libinput` udev helpers and rules) are not pulled in by anything in
   this package.
4. Nothing here has been exercised on the target hardware; §3.3's display
   behaviour in particular needs a real DRM handoff test.
