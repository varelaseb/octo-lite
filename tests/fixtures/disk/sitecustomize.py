"""Test fixture: a box disk as full as the file FAKE_DISK says, for the
command-time hook's disk warning (spec/domains/disk.spec.html#warning).

On PYTHONPATH, Python imports it at start, so the hook reads the root
filesystem as a 100 GiB disk, 5% kept for root as ext4 keeps it, whose df
Use% is the number FAKE_DISK holds; anything else there fails the read.
Every other path, and every run without FAKE_DISK, reads the real one.
"""

import os
from types import SimpleNamespace

_statvfs = os.statvfs


def statvfs(path):
    disk = os.environ.get("FAKE_DISK")
    if not disk or os.fspath(path) != "/":
        return _statvfs(path)
    with open(disk) as f:
        full = int(f.read())
    blocks = 100 * 2**30 // 4096
    usable = blocks * 95 // 100
    used = usable * full // 100
    return SimpleNamespace(f_frsize=4096, f_bsize=4096, f_blocks=blocks,
                           f_bfree=blocks - used, f_bavail=usable - used)


os.statvfs = statvfs
