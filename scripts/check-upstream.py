#!/usr/bin/env python3
"""
Check for a newer BuffyBox release and, with --write, update the packaging to
point at it: Version, the pinned buffybox + lvgl commits, lvgl version,
sources.sha256, the README pin table and a new %changelog stanza.

Security model (see README):
  * only tagged RELEASES from the GitLab API are considered - never a branch
    tip, never HEAD;
  * the release commit is taken from the releases API and then VERIFIED
    against the pax_global_header of the downloaded tag archive before
    anything is written;
  * the lvgl submodule commit is re-resolved AT THE NEW TAG, because a
    BuffyBox release may move it;
  * both archives are downloaded and hashed here; the sums are written to
    sources.sha256 and enforced at build time by scripts/fetch-sources.sh;
  * this script never commits, pushes or publishes. --write only edits files
    in the working tree for a human (or a PR workflow) to review.

Exit codes:
  0  up to date, or (with --write) files updated
  10 a newer release exists (without --write) - used by CI to decide whether
     to open a PR
  1  error
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import tarfile
import urllib.request
from datetime import timezone, datetime

PROJECT_ID = 172
GITLAB = "https://gitlab.postmarketos.org"
RELEASES_URL = f"{GITLAB}/api/v4/projects/{PROJECT_ID}/releases?per_page=20"
TREE_URL = f"{GITLAB}/api/v4/projects/{PROJECT_ID}/repository/tree?ref={{ref}}&per_page=100"
LVGL_VERSION_URL = "https://raw.githubusercontent.com/lvgl/lvgl/{commit}/lv_version.h"
BUFFYBOX_TARBALL = f"{GITLAB}/postmarketOS/buffybox/-/archive/{{v}}/buffybox-{{v}}.tar.gz"
LVGL_TARBALL = "https://github.com/lvgl/lvgl/archive/{commit}.tar.gz"

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(HERE, "buffybox-unl0kr.spec")
SUMS = os.path.join(HERE, "sources.sha256")
README = os.path.join(HERE, "README.md")

UA = {"User-Agent": "buffybox-unl0kr-fedora upstream-check"}

SHA1_RE = re.compile(r"[0-9a-f]{40}")

# sources.sha256 header, rendered fresh on every --write. It used to be copied
# forward verbatim, so after a bump it kept asserting the *previous* release's
# commit as "the reproducibility identity" - a silent provenance lie. Anything
# release-specific must be a substitution field here, never prose.
SUMS_HEADER = """\
# Pinned upstream source archives for buffybox-unl0kr.spec
#
# The COMMIT SHAs are the reproducibility identity:
#   buffybox  {ver}  -> {bb_commit}
#   lvgl      {lvgl_ver}  -> {lvgl_commit}
#
# The sha256 sums below are a tamper check. Auto-generated forge archives are
# content-immutable but not contractually byte-stable; if a sum ever drifts,
# verify the tree against the commit SHA before updating this file.
#
# Verify with:  sha256sum -c sources.sha256
# (run from the directory containing the downloaded archives)
"""


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (https only)
        return r.read()


def fetch_json(url: str):
    return json.loads(fetch(url).decode())


def version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def sub1(pattern, repl, text: str, what: str) -> str:
    """re.sub that aborts unless it matched exactly once. Every spec / README
    rewrite goes through this: a substitution that silently stops matching
    (because someone reflowed a line) is precisely how the pins drifted out of
    sync with reality in the first place."""
    new, n = re.subn(pattern, repl, text, flags=re.M)
    if n != 1:
        sys.exit(f"check-upstream: expected exactly 1 match for {what}, got {n}")
    return new


def spec_version() -> str:
    m = re.search(r"^Version:\s*(\S+)", pathlib.Path(SPEC).read_text(), re.M)
    if not m:
        sys.exit("could not read Version from spec")
    return m.group(1)


def latest_release() -> dict:
    rels = fetch_json(RELEASES_URL)
    # keep only plain X.Y.Z tags; ignore old per-component tags
    rels = [r for r in rels if re.fullmatch(r"\d+\.\d+\.\d+", r["tag_name"])]
    if not rels:
        sys.exit("no numeric releases found")
    rels.sort(key=lambda r: version_tuple(r["tag_name"]), reverse=True)
    return rels[0]


def buffybox_commit_of(rel: dict) -> str:
    """The commit the release tag points at: rel['commit']['id'].

    NOT the repository/tags API 'target' - for an annotated tag that is the
    sha of the tag object itself, not of the commit. It only happens to equal
    the commit for lightweight tags, so don't "simplify" this to use it.
    """
    sha = (rel.get("commit") or {}).get("id", "")
    if not SHA1_RE.fullmatch(sha):
        sys.exit(f"release {rel.get('tag_name')!r} has no usable commit id "
                 f"(got {sha!r})")
    return sha


def lvgl_commit_at(tag: str) -> str:
    for entry in fetch_json(TREE_URL.format(ref=tag)):
        if entry["name"] == "lvgl" and entry["type"] == "commit":
            return entry["id"]
    sys.exit(f"no lvgl submodule entry in tree at {tag}")


def lvgl_version_at(commit: str) -> str:
    txt = fetch(LVGL_VERSION_URL.format(commit=commit)).decode()
    parts = {}
    for key in ("MAJOR", "MINOR", "PATCH"):
        m = re.search(rf"LVGL_VERSION_{key}\s+(\d+)", txt)
        if not m:
            sys.exit("could not parse lv_version.h")
        parts[key] = m.group(1)
    return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['PATCH']}"


def pax_commit(blob: bytes) -> str:
    """GitLab records the source commit in the tag archive's pax_global_header
    as `comment=<sha>`. Read it back so the commit the releases API reported
    is checked against the bytes we are about to hash and pin."""
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        sha = tf.pax_headers.get("comment", "")
    if not SHA1_RE.fullmatch(sha):
        sys.exit(f"tag archive carries no commit in its pax header (got {sha!r})")
    return sha


def sha256_of(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def rewrite_spec(new_ver: str, bb_commit: str,
                 lvgl_commit: str, lvgl_ver: str) -> None:
    s = pathlib.Path(SPEC).read_text()
    s = sub1(r"^(%global buffybox_commit\s+)\S+", rf"\g<1>{bb_commit}", s,
             "%global buffybox_commit")
    s = sub1(r"^(%global lvgl_commit\s+)\S+", rf"\g<1>{lvgl_commit}", s,
             "%global lvgl_commit")
    s = sub1(r"^(%global lvgl_version\s+)\S+", rf"\g<1>{lvgl_ver}", s,
             "%global lvgl_version")
    s = sub1(r"^(Version:\s*)\S+", rf"\g<1>{new_ver}", s, "Version:")
    s = sub1(r"^(Release:\s*)\d+", r"\g<1>1", s, "Release:")

    stamp = datetime.now(timezone.utc).strftime("%a %b %d %Y")
    entry = (
        f"* {stamp} upstream-check <noreply@localhost> - {new_ver}-1\n"
        f"- Update to BuffyBox {new_ver} (commit {bb_commit})\n"
        f"- lvgl bundled at {lvgl_commit} (upstream v{lvgl_ver})\n\n"
    )
    s = sub1(r"^%changelog\n", lambda m: m.group(0) + entry, s,
             "%changelog anchor")
    pathlib.Path(SPEC).write_text(s)


def sums_header(ver: str, bb_commit: str,
                lvgl_ver: str, lvgl_commit: str) -> str:
    return SUMS_HEADER.format(ver=ver, bb_commit=bb_commit,
                              lvgl_ver=lvgl_ver, lvgl_commit=lvgl_commit)


def rewrite_sums(new_ver: str, bb_commit: str, lvgl_commit: str, lvgl_ver: str,
                 bb_sha: str, lvgl_sha: str) -> None:
    body = (
        f"{bb_sha}  buffybox-{new_ver}.tar.gz\n"
        f"{lvgl_sha}  lvgl-{lvgl_commit}.tar.gz\n"
    )
    pathlib.Path(SUMS).write_text(
        sums_header(new_ver, bb_commit, lvgl_ver, lvgl_commit) + "\n" + body
    )


def rewrite_readme(new_ver: str, bb_commit: str,
                   lvgl_commit: str, lvgl_ver: str) -> None:
    """The README section 3 table is a human-readable mirror of the identity
    that lives canonically in the spec; keep it in step on every bump."""
    s = pathlib.Path(README).read_text()
    s = sub1(
        r"^\| BuffyBox \| tag \*\*`[^`]+`\*\*, commit `[0-9a-f]+` \|",
        f"| BuffyBox | tag **`{new_ver}`**, commit `{bb_commit}` |",
        s, "README BuffyBox pin row")
    s = sub1(
        r"^\| LVGL \(bundled, static\) \| commit `[0-9a-f]+` = \*\*v[^*]+\*\* \|",
        f"| LVGL (bundled, static) | commit `{lvgl_commit}` = **v{lvgl_ver}** |",
        s, "README LVGL pin row")
    pathlib.Path(README).write_text(s)


def gh_output(**kw) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as fh:
        for k, v in kw.items():
            fh.write(f"{k}={v}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="update spec + sources.sha256 + README in place")
    args = ap.parse_args()

    cur = spec_version()
    rel = latest_release()
    new = rel["tag_name"]

    print(f"packaged : {cur}")
    print(f"upstream : {new}  ({rel.get('released_at', '?')})")

    if version_tuple(new) <= version_tuple(cur):
        print("up to date")
        gh_output(update="false")
        return 0

    bb_commit = buffybox_commit_of(rel)
    lvgl_commit = lvgl_commit_at(new)
    lvgl_ver = lvgl_version_at(lvgl_commit)
    print(f"buffybox : {bb_commit}")
    print(f"lvgl     : {lvgl_commit}  (v{lvgl_ver})")

    if not args.write:
        print("\nnewer release available; re-run with --write to update files")
        gh_output(update="true", new_version=new, buffybox_commit=bb_commit,
                  lvgl_commit=lvgl_commit, lvgl_version=lvgl_ver)
        return 10

    print("downloading + hashing archives ...")
    bb_blob = fetch(BUFFYBOX_TARBALL.format(v=new))
    # Verify BEFORE any file is touched: on a mismatch the tree stays clean.
    archived = pax_commit(bb_blob)
    if archived != bb_commit:
        sys.exit(f"commit mismatch: releases API reports {bb_commit} for "
                 f"{new}, but the tag archive was cut from {archived}")
    lvgl_blob = fetch(LVGL_TARBALL.format(commit=lvgl_commit))
    bb_sha = sha256_of(bb_blob)
    lvgl_sha = sha256_of(lvgl_blob)
    print(f"  buffybox-{new}.tar.gz  {bb_sha}")
    print(f"  lvgl-{lvgl_commit}.tar.gz  {lvgl_sha}")

    rewrite_spec(new, bb_commit, lvgl_commit, lvgl_ver)
    rewrite_sums(new, bb_commit, lvgl_commit, lvgl_ver, bb_sha, lvgl_sha)
    rewrite_readme(new, bb_commit, lvgl_commit, lvgl_ver)
    print("\nupdated buffybox-unl0kr.spec, sources.sha256 and README.md")
    print("review the diff, then let CI build it")
    gh_output(update="true", new_version=new, buffybox_commit=bb_commit,
              lvgl_commit=lvgl_commit, lvgl_version=lvgl_ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
