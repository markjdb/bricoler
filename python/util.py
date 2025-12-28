#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import functools
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional


@contextmanager
def chdir(dir: Path, **kwargs):
    old_dir = Path.cwd()
    dir.mkdir(parents=True, exist_ok=True, **kwargs)
    os.chdir(dir)
    try:
        yield
    finally:
        os.chdir(old_dir)


@functools.cache
def host_machine() -> str:
    return sysctl("hw.machine") + "/" + sysctl("hw.machine_arch")


def sysctl(name: str) -> str:
    result = run_cmd(["sysctl", "-n", name], capture_output=True, text=True)
    return result.stdout.strip()


def run_cmd(cmd: List[str], *args, env: Optional[Dict[str, str]] = None, **kwargs):
    cmd = [str(c) for c in cmd]
    if not os.getenv("BRICOLER_ARGCOMPLETE"):
        print(f"EXEC: '{' '.join(cmd)}'")
    if env is not None:
        tmp = os.environ.copy()
        tmp.update(env)
        env = tmp
        assert kwargs.get('env') is None
        kwargs['env'] = env
    result = subprocess.run(cmd, *args, **kwargs, check=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(result.stderr)}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result
