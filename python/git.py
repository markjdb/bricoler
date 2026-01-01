#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from util import run_cmd


class GitRepository:
    def __init__(self, url: str, branch: Optional[str] = None):
        self.url = url
        self.branch = branch

        # If the URL has no scheme, assume it's a local path and skip cloning.
        parsed = urlparse(url)
        self.skip_clone = parsed.scheme == ''
        if self.skip_clone:
            self.url = self.path = Path(url).resolve()

    def git(self, args: List[str]):
        if not self.path:
            raise ValueError("Repository has not been cloned yet")
        return run_cmd(
            ['git', '-C', self.path] + args,
            capture_output=True
        )

    def clone(self, path: Path):
        if (path / ".git").is_dir():
            if self.skip_clone:
                return

            # Already cloned.  Make sure the correct branch is checked out.
            for name, url in self.remotes.items():
                if url == self.url:
                    remote = name
                    break
            else:
                raise ValueError(
                    f"Clone at '{path}' has no remote corresponding to '{self.url}'"
                )
            self.git(["fetch", remote])
            self.git(["checkout", f"{remote}/{self.branch}"])
        elif self.skip_clone:
            raise ValueError(
                f"Repository path '{self.url}' does not exist or is not a repo clone"
            )
        else:
            cmd = ["git", "clone", "--depth=1"]
            if self.branch:
                cmd += ["--branch", self.branch]
            cmd += [self.url, str(path.resolve())]
            run_cmd(cmd)
        self.path = path.resolve()

    @property
    def remotes(self) -> Dict[str, str]:
        result = {}
        output = self.git(["remote", "-v"])
        for line in output.stdout.decode().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name = parts[0]
            url = parts[1]
            result[name] = url
        return result
