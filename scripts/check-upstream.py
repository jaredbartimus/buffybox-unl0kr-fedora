#!/usr/bin/env python3
"""
Check for a newer BuffyBox release and, with --write, update the packaging to
point at it: Version, the pinned lvgl commit/version, sources.sha256 and a new
%changelog stanza.

Security model (see README):
  * only tagged RELEASES from the GitLab API are considered - never a branch
    tip, never HEAD;
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
import json
import os
import re
import sys
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

UA = {"User-Agent": "buffybox-unl0kr-fedora upstream-check"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (https only)
        return r.read()


def fetch_json(url: str):
    return json.loads(fetch(url).decode())


def version_tuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def spec_version() -> str:
    m = re.search(r"^Version:\s*(\S+)", open(SPEC).read(), re.M)
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


def sha256_of_url(url: str) -> str:
    h = hashlib.sha256()
    h.update(fetch(url))
    return h.hexdigest()


def rewrite_spec(new_ver: str, lvgl_commit: str, lvgl_ver: str) -> None:
    s = open(SPEC).read()
    s = re.sub(r"^(%global lvgl_commit\s+)\S+", rf"\g<1>{lvgl_commit}", s, flags=re.M)
    s = re.sub(r"^(%global lvgl_version\s+)\S+", rf"\g<1>{lvgl_ver}", s, flags=re.M)
    s = re.sub(r"^(Version:\s*)\S+", rf"\g<1>{new_ver}", s, flags=re.M)
    s = re.sub(r"^(Release:\s*)\d+", r"\g<1>1", s, flags=re.M)

    stamp = datetime.now(timezone.utc).strftime("%a %b %d %Y")
    entry = (
        f"* {stamp} upstream-check <noreply@localhost> - {new_ver}-1\n"
        f"- Update to BuffyBox {new_ver}\n"
        f"- lvgl bundled at {lvgl_commit} (upstream v{lvgl_ver})\n\n"
    )
    s = re.sub(r"(^%changelog\n)", r"\1" + entry, s, flags=re.M, count=1)
    open(SPEC, "w").write(s)


def rewrite_sums(new_ver: str, lvgl_commit: str,
                 bb_sha: str, lvgl_sha: str) -> None:
    comments = [ln for ln in open(SUMS) if ln.startswith("#")]
    header = "".join(comments).rstrip("\n") + "\n\n"
    body = (
        f"{bb_sha}  buffybox-{new_ver}.tar.gz\n"
        f"{lvgl_sha}  lvgl-{lvgl_commit}.tar.gz\n"
    )
    open(SUMS, "w").write(header + body)


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
                    help="update spec + sources.sha256 in place")
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

    lvgl_commit = lvgl_commit_at(new)
    lvgl_ver = lvgl_version_at(lvgl_commit)
    print(f"lvgl     : {lvgl_commit}  (v{lvgl_ver})")

    if not args.write:
        print("\nnewer release available; re-run with --write to update files")
        gh_output(update="true", new_version=new, lvgl_commit=lvgl_commit,
                  lvgl_version=lvgl_ver)
        return 10

    print("downloading + hashing archives ...")
    bb_sha = sha256_of_url(BUFFYBOX_TARBALL.format(v=new))
    lvgl_sha = sha256_of_url(LVGL_TARBALL.format(commit=lvgl_commit))
    print(f"  buffybox-{new}.tar.gz  {bb_sha}")
    print(f"  lvgl-{lvgl_commit}.tar.gz  {lvgl_sha}")

    rewrite_spec(new, lvgl_commit, lvgl_ver)
    rewrite_sums(new, lvgl_commit, bb_sha, lvgl_sha)
    print("\nupdated buffybox-unl0kr.spec and sources.sha256")
    print("review the diff, then let CI build it")
    gh_output(update="true", new_version=new, lvgl_commit=lvgl_commit,
              lvgl_version=lvgl_ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
