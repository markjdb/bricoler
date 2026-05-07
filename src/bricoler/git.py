#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .util import run_cmd


class GitRepository:
    @staticmethod
    def is_ssh_url(url: str) -> bool:
        # Simple check for SSH-style Git URLs.  This doesn't match git's exact
        # behaviour but it seems close enough that it won't matter.
        colon = url.find(":")
        if colon == -1:
            return False
        slash = url.find("/")
        return slash == -1 or colon < slash

    def __init__(
        self,
        url: str,
        path: Path,
        branch: str | None = None,
        shallow: bool = True,
        no_cmds: bool = False,
    ) -> None:
        self.url = url
        self.branch = branch
        self._no_cmds = no_cmds

        parsed = urlparse(url)
        self.external = parsed.scheme == "" and not self.is_ssh_url(url)
        if self.external:
            self.path = Path(url).resolve()
        else:
            self.path = path.resolve()
        self.clone(shallow=shallow)

    def git(self, cmd: list[str], *args, **kwargs):
        if not self.path:
            raise ValueError("Repository has not been cloned yet")
        return run_cmd(["git", "-C", self.path] + cmd, *args, **kwargs)

    def checked_out_branch(self) -> str:
        return (
            self.git(["rev-parse", "--abbrev-ref", "HEAD"], capture_output=True)
            .stdout.decode()
            .strip()
        )

    def checked_out_revision(self) -> str:
        return (
            self.git(["rev-parse", "HEAD"], capture_output=True).stdout.decode().strip()
        )

    def isshallow(self) -> bool:
        output = self.git(["rev-parse", "--is-shallow-repository"], capture_output=True)
        return output.stdout.decode().strip() == "true"

    def clone(self, shallow=True) -> None:
        if not (self.path / ".git").exists():
            if self.external:
                raise ValueError(
                    f"Repository path '{self.url}' does not exist or is not a repo clone",
                )
            cmd = ["git", "clone"]
            if shallow:
                cmd += ["--depth=1"]
            if self.branch:
                cmd += ["--branch", self.branch]
            cmd += [self.url, str(self.path.resolve())]
            run_cmd(cmd)

    def update(self, shallow=True) -> None:
        assert self.path is not None
        if self.external:
            # This repository is externally managed.
            return
        if self._no_cmds:
            return

        for name, url in self.remotes.items():
            if url == self.url:
                remote = name
                break
        else:
            raise ValueError(
                f"Clone at '{self.path}' has no remote corresponding to '{self.url}'",
            )
        if shallow or not self.isshallow():
            self.git(["fetch", remote])
        else:
            self.git(["fetch", "--unshallow", remote])
        self.git(["checkout", f"{self.branch}"])
        self.git(["merge", "--ff-only", remote, f"{self.branch}"])

    @property
    def remotes(self) -> dict[str, str]:
        result = {}
        output = self.git(["remote", "-v"], capture_output=True)
        for line in output.stdout.decode().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[0]
            url = parts[1]
            result[name] = url
        return result

    @property
    def revision(self) -> str:
        output = self.git(["rev-parse", "HEAD"])
        return output.stdout.decode().strip()
