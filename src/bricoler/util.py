#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

from __future__ import annotations

import functools
import os
import signal
import socket
import subprocess
import sys
from contextlib import contextmanager
from enum import Enum
from pathlib import Path


class EmailReport:
    def __init__(
        self, subject: str, body: str, attachments: list[Path] | None = None
    ) -> None:
        self.subject = subject
        self.body = body
        self.attachments = attachments or []

    def send(self, mail_to: str, mail_from: str) -> None:
        msg = (
            f"From: {mail_from}\nTo: {mail_to}\nSubject: {self.subject}\n\n{self.body}"
        )

        for attachment in self.attachments:
            with attachment.open("rb") as f:
                content = f.read()
                msg += f"\n\nAttachment: {attachment.name}\n{content.decode(errors='replace')}"

        subprocess.run(
            ["sendmail", "-t", "-f", mail_from],
            input=msg.encode(),
            check=True,
        )


class ANSIColour(Enum):
    BLACK = (30,)
    RED = (31,)
    GREEN = (32,)
    YELLOW = (33,)
    BLUE = (34,)
    MAGENTA = (35,)
    CYAN = (36,)
    WHITE = (37,)


def colour(text: str, colour: ANSIColour) -> str:
    return f"\033[{colour.value[0]}m{text}\033[0m"


@contextmanager
def chdir(path: Path, **kwargs):
    old_dir = Path.cwd()
    path.mkdir(parents=True, exist_ok=True, **kwargs)
    os.chdir(path)
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
    cmd: list,
    *args,
    env: dict[str, str] | None = None,
    check_result: bool = True,
    skip: bool = False,
    **kwargs,
):
    cmd = [str(c) for c in cmd]
    cmdstr = " ".join(cmd)
    log = not kwargs.get("capture_output", False)
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
        assert kwargs.get("env") is None
        kwargs["env"] = env

    capture_output = kwargs.pop("capture_output", False)
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    new_pgrp = kwargs.get("process_group") == 0
    old_pgrp = None
    old_sigttou = None
    if new_pgrp and sys.stdin.isatty():
        fd = sys.stdin.fileno()
        old_pgrp = os.tcgetpgrp(fd)
        old_sigttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)

    with subprocess.Popen(cmd, *args, **kwargs) as process:
        if new_pgrp and old_pgrp is not None:
            os.tcsetpgrp(fd, process.pid)

        try:
            stdout, stderr = process.communicate()
            returncode = process.returncode
        finally:
            if old_pgrp is not None:
                os.tcsetpgrp(fd, old_pgrp)
                signal.signal(signal.SIGTTOU, old_sigttou)

    result = subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    if check_result and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def info(message: str) -> None:
    print(colour("INFO", ANSIColour.GREEN) + f": {message}")


def warn(message: str) -> None:
    print(colour("WARN", ANSIColour.YELLOW) + f": {message}", file=sys.stderr)


def unused_tcp_addr() -> tuple[str, int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()
