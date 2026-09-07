#!/bin/bash
# dracut module for unl0kr

check() {
    # The module can only be included if the required binaries are present.
    require_binaries /usr/bin/unl0kr /usr/libexec/unl0kr-agent || return 1

    # Return 255 to ensure this module is NOT included by default.
    # It must be explicitly requested via add_dracutmodules+=" unl0kr ".
    return 255
}

depends() {
    # unl0kr-agent integrates directly with the systemd ask-password protocol.
    # systemd runs the units; systemd-ask-password provides the early-boot ask-password directory.
    echo systemd systemd-ask-password
    return 0
}

install() {
    # Use inst_binary for executables to automatically resolve and include
    # all required ELF shared library dependencies.
    inst_binary /usr/bin/unl0kr
    inst_binary /usr/libexec/unl0kr-agent
    
    # Configuration files
    inst_simple /etc/unl0kr.conf
    if ls /etc/unl0kr.conf.d/*.conf >/dev/null 2>&1; then
        inst_multiple /etc/unl0kr.conf.d/*.conf
    fi

    # The required systemd units
    inst_simple /usr/lib/systemd/system/unl0kr-agent.path
    inst_simple /usr/lib/systemd/system/unl0kr-agent.service

    # Enable the agent path unit in the initramfs.
    # shellcheck disable=SC2154
    $SYSTEMCTL -q --root "$initdir" enable unl0kr-agent.path

    # libinput dependencies (quirks and udev helpers)
    inst_multiple -o \
        /usr/share/libinput/*.quirks \
        /usr/lib/udev/libinput-*
    
    inst_rules 80-libinput-device-groups.rules 90-libinput-fuzz-override.rules

    # XKB data required for keyboard layouts
    # Unl0kr uses xkbcommon which strictly requires the /usr/share/X11/xkb structure.
    # Dracut provides no built-in recursive install function, so we iterate
    # over the tree using inst_simple to respect dracut staging constraints.
    if [ -d /usr/share/X11/xkb ]; then
        find /usr/share/X11/xkb/ \( -type f -o -type l \) 2>/dev/null | while IFS= read -r f; do
            inst_simple "$f"
        done
    fi

    # TODO: Implement a runtime helper to identify the DRM card associated with
    # the internal panel (e.g. eDP) and set LV_LINUX_DRM_CARD in a wrapper script or drop-in.
    # Hard-coding a specific DRM card is not a stable interface and is omitted here.
}
