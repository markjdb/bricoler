#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

from pathlib import Path
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

from .util import run_cmd


class GitRepository:
    @staticmethod
    def is_ssh_url(url: str) -> bool:
        # Simple check for SSH-style Git URLs.  This doesn't match git's exact
        # behaviour but it seems close enough that it won't matter.
        colon = url.find(':')
        if colon == -1:
            return False
        slash = url.find('/')
        return slash == -1 or colon < slash

    def __init__(
        self,
        url: str,
        path: Path,
        branch: Optional[str] = None,
        no_cmds: bool = False,
    ):
        self.url = url
        self.branch = branch
        self._no_cmds = no_cmds

        parsed = urlparse(url)
        self.external = parsed.scheme == '' and not self.is_ssh_url(url)
        if self.external:
            self.path = Path(url).resolve()
        else:
            self.path = path.resolve()
        self.clone()

    def git(self, cmd: List[str], *args, **kwargs):
        if not self.path:
            raise ValueError("Repository has not been cloned yet")
        return run_cmd(['git', '-C', self.path] + cmd, *args, **kwargs)

    def clone(self):
        if not (self.path / ".git").exists():
            if self.external:
                raise ValueError(
                    f"Repository path '{self.url}' does not exist or is not a repo clone"
                )
            cmd = ["git", "clone", "--depth=1"]
            if self.branch:
                cmd += ["--branch", self.branch]
            cmd += [self.url, str(self.path.resolve())]
            run_cmd(cmd)

    def update(self):
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
                f"Clone at '{self.path}' has no remote corresponding to '{self.url}'"
            )
        self.git(["fetch", remote])
        self.git(["checkout", f"{self.branch}"])
        self.git(["merge", "--ff-only", remote, f"{self.branch}"])

    @property
    def remotes(self) -> Dict[str, str]:
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
