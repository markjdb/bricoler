#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import functools
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ANSIColour(Enum):
    BLACK = 30,
    RED = 31,
    GREEN = 32,
    YELLOW = 33,
    BLUE = 34,
    MAGENTA = 35,
    CYAN = 36,
    WHITE = 37,


def colour(text: str, colour: ANSIColour) -> str:
    return f"\033[{colour.value[0]}m{text}\033[0m"


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


def run_cmd(
    cmd: List[Any],
    *args,
    env: Optional[Dict[str, str]] = None,
    check_result: bool = True,
    skip: bool = False,
    **kwargs
):
    cmd = [str(c) for c in cmd]
    cmdstr = ' '.join(cmd)
    log = not kwargs.get('capture_output', False)
    if skip:
        if log:
            info(f"EXEC(skipped): '{cmdstr}'")
        return subprocess.CompletedProcess(cmd, 0)
    if log:
        info(f"EXEC: '{cmdstr}'")
    if env is not None:
        tmp = os.environ.copy()
        tmp.update(env)
        env = tmp
        assert kwargs.get('env') is None
        kwargs['env'] = env
    result = subprocess.run(cmd, *args, **kwargs)
    if check_result and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def info(message: str):
    print(colour("INFO", ANSIColour.GREEN) + f": {message}")


def warn(message: str):
    print(colour("WARN", ANSIColour.YELLOW) + f": {message}", file=sys.stderr)


def unused_tcp_addr() -> Tuple[str, int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()
