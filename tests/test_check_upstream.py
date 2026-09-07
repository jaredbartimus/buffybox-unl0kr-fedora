#!/usr/bin/env python3
"""
Offline tests for scripts/check-upstream.py.

The script's whole job is to keep the packaging's stated provenance in step
with the release it points at. The bug these tests exist for: --write bumped
Version and the lvgl pin but left `%global buffybox_commit` (and the
sources.sha256 header, and the README pin table) frozen at the previous
release, so an automated PR shipped a package whose recorded identity was a
lie.

No network: every fetch goes through the module-level `fetch`, which each test
replaces with a URL->bytes registry.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check-upstream.py"

# The identity currently committed to the tree.
CUR_VER = "3.6.0"
OLD_BB = "d0f52495f7f3afa8839eef4b19f43f4ca1243107"
OLD_LVGL = "85aa60d18b3d5e5588d7b247abf90198f07c8a63"

# Fabricated but well-formed pins for simulated bumps.
BB_37 = "1111111111111111111111111111111111111111"
LV_37 = "2222222222222222222222222222222222222222"
BB_38 = "3333333333333333333333333333333333333333"
LV_38 = "4444444444444444444444444444444444444444"


def load_module():
    """Fresh module instance per test - each one repoints SPEC/SUMS/README and
    monkeypatches `fetch`, and must not leak that into the next."""
    spec = importlib.util.spec_from_file_location("check_upstream_under_test",
                                                  SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def releases_json(*pairs):
    """pairs: (tag, commit_id), newest first is fine - the script sorts."""
    return json.dumps([
        {"tag_name": tag,
         "released_at": "2026-01-02T03:04:05Z",
         "commit": {"id": commit}}
        for tag, commit in pairs
    ]).encode()


def tree_json(lvgl_commit):
    return json.dumps([
        {"name": "COPYING", "type": "blob", "id": "f" * 40},
        {"name": "lvgl", "type": "commit", "id": lvgl_commit},
        {"name": "meson.build", "type": "blob", "id": "e" * 40},
    ]).encode()


def lv_version_h(ver):
    major, minor, patch = ver.split(".")
    return (
        f"#define LVGL_VERSION_MAJOR {major}\n"
        f"#define LVGL_VERSION_MINOR {minor}\n"
        f"#define LVGL_VERSION_PATCH {patch}\n"
        '#define LVGL_VERSION_INFO ""\n'
    ).encode()


def bb_tarball(commit):
    """A real .tar.gz whose pax_global_header carries `comment=<commit>`,
    exactly like GitLab's tag archives."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers={"comment": commit}) as tf:
        payload = b"buffybox source tree\n"
        info = tarfile.TarInfo("buffybox-x/meson.build")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class CheckUpstreamTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="check-upstream-test.")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self.spec = os.path.join(self.tmp, "buffybox-unl0kr.spec")
        self.sums = os.path.join(self.tmp, "sources.sha256")
        self.readme = os.path.join(self.tmp, "README.md")
        self.gh_output = os.path.join(self.tmp, "gh_output")
        shutil.copy(REPO / "buffybox-unl0kr.spec", self.spec)
        shutil.copy(REPO / "sources.sha256", self.sums)
        shutil.copy(REPO / "README.md", self.readme)

        self.orig = {p: pathlib.Path(p).read_bytes()
                     for p in (self.spec, self.sums, self.readme)}

        self.mod = load_module()
        self.mod.SPEC = self.spec
        self.mod.SUMS = self.sums
        self.mod.README = self.readme

    # --- helpers ------------------------------------------------------------

    def run_main(self, argv, registry):
        def fake_fetch(url):
            if url not in registry:
                raise AssertionError(f"unexpected fetch: {url}")
            return registry[url]

        self.mod.fetch = fake_fetch
        out = io.StringIO()
        env = {"GITHUB_OUTPUT": self.gh_output}
        with mock.patch.object(sys, "argv", ["check-upstream.py", *argv]), \
             mock.patch.dict(os.environ, env), \
             contextlib.redirect_stdout(out):
            code = self.mod.main()
        return code, out.getvalue()

    def registry(self, releases, new_ver, bb_commit, lvgl_commit, lvgl_ver,
                 pax_commit=None):
        m = self.mod
        return {
            m.RELEASES_URL: releases_json(*releases),
            m.TREE_URL.format(ref=new_ver): tree_json(lvgl_commit),
            m.LVGL_VERSION_URL.format(commit=lvgl_commit): lv_version_h(lvgl_ver),
            m.BUFFYBOX_TARBALL.format(v=new_ver):
                bb_tarball(pax_commit or bb_commit),
            m.LVGL_TARBALL.format(commit=lvgl_commit): b"lvgl archive bytes\n",
        }

    def assert_files_untouched(self):
        for path, data in self.orig.items():
            self.assertEqual(pathlib.Path(path).read_bytes(), data,
                             f"{os.path.basename(path)} was modified")

    def read(self, path):
        return pathlib.Path(path).read_text()

    # --- 1: already current ----------------------------------------------------

    def test_up_to_date_touches_nothing(self):
        reg = {self.mod.RELEASES_URL: releases_json((CUR_VER, OLD_BB),
                                                    ("3.5.1", "a" * 40))}
        code, out = self.run_main(["--write"], reg)
        self.assertEqual(code, 0)
        self.assertIn("up to date", out)
        self.assert_files_untouched()

    # --- 2: newer, reporting only -------------------------------------------

    def test_report_only_emits_buffybox_commit_and_writes_nothing(self):
        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0")
        code, _ = self.run_main([], reg)
        self.assertEqual(code, 10)
        self.assert_files_untouched()
        emitted = self.read(self.gh_output)
        self.assertIn(f"buffybox_commit={BB_37}", emitted)
        self.assertIn("new_version=3.7.0", emitted)

    # --- 3: the simulated release bump -----------------------------------------

    def test_write_bumps_every_provenance_site(self):
        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0")
        code, out = self.run_main(["--write"], reg)
        self.assertEqual(code, 0)
        self.assertIn("updated buffybox-unl0kr.spec, sources.sha256 and README.md",
                      out)

        spec = self.read(self.spec)
        self.assertRegex(spec, r"(?m)^Version:\s*3\.7\.0\b")
        self.assertRegex(spec, r"(?m)^Release:\s*1%\{\?dist\}")
        self.assertRegex(spec, rf"(?m)^%global buffybox_commit\s+{BB_37}$")
        self.assertRegex(spec, rf"(?m)^%global lvgl_commit\s+{LV_37}$")
        self.assertRegex(spec, r"(?m)^%global lvgl_version\s+9\.6\.0$")
        # changelog stanza names both commits, is prepended (newest first)
        self.assertIn(f"- Update to BuffyBox 3.7.0 (commit {BB_37})", spec)
        self.assertIn(f"- lvgl bundled at {LV_37} (upstream v9.6.0)", spec)
        self.assertLess(spec.index("3.7.0-1"), spec.index("3.6.0-1"))
        # old buffybox commit is gone entirely (it lived only in %global)
        self.assertNotIn(OLD_BB, spec)

        sums = self.read(self.sums)
        self.assertIn(f"  buffybox  3.7.0  -> {BB_37}", sums)
        self.assertIn(f"  lvgl      9.6.0  -> {LV_37}", sums)
        self.assertRegex(sums, rf"(?m)^\w{{64}}  buffybox-3\.7\.0\.tar\.gz$")
        self.assertRegex(sums, rf"(?m)^\w{{64}}  lvgl-{LV_37}\.tar\.gz$")
        self.assertNotIn(OLD_BB, sums)
        self.assertNotIn(OLD_LVGL, sums)
        self.assertNotIn("3.6.0", sums)
        # the version-specific "As of the 3.6.0 packaging ..." sentence is gone
        self.assertNotIn("As of the", sums)

        readme = self.read(self.readme)
        self.assertIn(
            f"| BuffyBox | tag **`3.7.0`**, commit `{BB_37}` | GitLab tag archive |",
            readme)
        self.assertIn(
            f"| LVGL (bundled, static) | commit `{LV_37}` = **v9.6.0** "
            f"| GitHub commit archive |",
            readme)
        self.assertNotIn(OLD_BB, readme)
        self.assertNotIn(OLD_LVGL, readme)

    # --- 4: two bumps in a row (the rewrite_sums discriminator) ---------------

    def test_double_bump_leaves_no_accreted_header(self):
        reg1 = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                             "3.7.0", BB_37, LV_37, "9.6.0")
        self.assertEqual(self.run_main(["--write"], reg1)[0], 0)
        reg2 = self.registry([("3.8.0", BB_38), ("3.7.0", BB_37)],
                             "3.8.0", BB_38, LV_38, "9.7.0")
        self.assertEqual(self.run_main(["--write"], reg2)[0], 0)

        sums = self.read(self.sums)
        # header regenerated, not carried forward: still exactly 12 comment
        # lines, and it names only the current pins.
        self.assertEqual(sum(1 for ln in sums.splitlines()
                             if ln.startswith("#")), 12)
        self.assertEqual(sums.count("buffybox  "), 1)
        self.assertEqual(sums.count("-> "), 2)
        for stale in (OLD_BB, OLD_LVGL, BB_37, LV_37, "3.7.0", "3.6.0"):
            self.assertNotIn(stale, sums, f"{stale} survived into sums")

        # spec changelog keeps every stanza; body pins are current
        spec = self.read(self.spec)
        self.assertRegex(spec, rf"(?m)^%global buffybox_commit\s+{BB_38}$")
        self.assertIn("3.8.0-1", spec)
        self.assertIn("3.7.0-1", spec)
        self.assertIn("3.6.0-1", spec)

    # --- 5: pax header contradicts the API -----------------------------------

    def test_pax_mismatch_aborts_before_any_write(self):
        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0",
                            pax_commit=BB_38)  # archive says something else
        with self.assertRaises(SystemExit) as cm:
            self.run_main(["--write"], reg)
        self.assertNotEqual(cm.exception.code, 0)
        self.assert_files_untouched()

    # --- 6: a substitution silently stops matching --------------------------

    def test_missing_global_line_is_a_hard_error(self):
        text = self.read(self.spec)
        text = re.sub(r"(?m)^%global buffybox_commit .*\n", "", text)
        pathlib.Path(self.spec).write_text(text)
        self.orig[self.spec] = pathlib.Path(self.spec).read_bytes()

        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0")
        with self.assertRaises(SystemExit) as cm:
            self.run_main(["--write"], reg)
        self.assertIn("buffybox_commit", str(cm.exception.code))
        self.assert_files_untouched()

    # --- 7: release JSON has no usable commit id ----------------------------

    def test_malformed_commit_id_aborts_before_any_write(self):
        m = self.mod
        reg = {
            m.RELEASES_URL: json.dumps([
                {"tag_name": "3.7.0", "released_at": "x",
                 "commit": {"id": "not-a-sha"}},
                {"tag_name": CUR_VER, "commit": {"id": OLD_BB}},
            ]).encode(),
            m.TREE_URL.format(ref="3.7.0"): tree_json(LV_37),
            m.LVGL_VERSION_URL.format(commit=LV_37): lv_version_h("9.6.0"),
        }
        with self.assertRaises(SystemExit):
            self.run_main(["--write"], reg)
        self.assert_files_untouched()

    # --- 8: the rewritten spec is still parseable by fetch-sources.sh -------

    def test_rewritten_spec_still_parses_with_shell_extractors(self):
        if not shutil.which("sed"):
            self.skipTest("sed not available")
        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0")
        self.assertEqual(self.run_main(["--write"], reg)[0], 0)

        # the exact sed programs from scripts/fetch-sources.sh
        def sed_global(name):
            prog = (rf"s/^%global[[:space:]]\+{name}[[:space:]]\+"
                    r"\([^[:space:]]\+\).*/\1/p")
            return subprocess.run(["sed", "-n", prog, self.spec],
                                  capture_output=True, text=True,
                                  check=True).stdout.splitlines()[0]

        def sed_tag(name):
            prog = rf"s/^{name}:[[:space:]]*\([^[:space:]]\+\).*/\1/p"
            return subprocess.run(["sed", "-n", prog, self.spec],
                                  capture_output=True, text=True,
                                  check=True).stdout.splitlines()[0]

        self.assertEqual(sed_global("buffybox_commit"), BB_37)
        self.assertEqual(sed_global("lvgl_commit"), LV_37)
        self.assertEqual(sed_tag("Version"), "3.7.0")

    # --- 9: committed sources.sha256 header == what the template renders ----

    def test_committed_sums_header_matches_template(self):
        committed = (REPO / "sources.sha256").read_text()
        rendered = self.mod.sums_header(CUR_VER, OLD_BB, "9.5.0", OLD_LVGL)
        self.assertTrue(
            committed.startswith(rendered + "\n"),
            "sources.sha256 header has drifted from SUMS_HEADER; regenerate it\n"
            f"--- committed ---\n{committed[:600]}")

    # --- 10: sweep - no stale identity string survives a bump ---------------

    def test_no_stale_identity_strings_after_bump(self):
        reg = self.registry([("3.7.0", BB_37), (CUR_VER, OLD_BB)],
                            "3.7.0", BB_37, LV_37, "9.6.0")
        self.assertEqual(self.run_main(["--write"], reg)[0], 0)

        spec = self.read(self.spec)
        sums = self.read(self.sums)
        readme = self.read(self.readme)

        # sources.sha256: nothing stale at all
        for stale in (OLD_BB, OLD_LVGL, "3.6.0"):
            self.assertNotIn(stale, sums)

        # spec: old SHAs and the old version only survive inside %changelog
        changelog = spec[spec.index("%changelog"):]
        body = spec[:spec.index("%changelog")]
        for stale in (OLD_BB, OLD_LVGL):
            self.assertNotIn(stale, body)
        self.assertNotIn(OLD_BB, changelog)          # never was there; stays gone
        self.assertIn(OLD_LVGL, changelog)           # historical stanza keeps it

        # README: the machine-managed pin table carries no old SHA. Prose
        # references to "3.6.0" elsewhere are historical narrative, deliberately
        # out of scope for rewrite_readme.
        for stale in (OLD_BB, OLD_LVGL):
            self.assertNotIn(stale, readme)


if __name__ == "__main__":
    unittest.main()
