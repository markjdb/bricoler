# bricoler

bricoler is a utility for running FreeBSD src development workflows.
The basic idea is to simplify common src development tasks by provding a framework to wrap operations like:
- building a FreeBSD src tree,
- constructing a VM image from the output of a build,
- booting the VM image (using QEMU or bhyve),
- running things in the guest once it has booted.

-----

## Table of Contents

- [Installation](#installation)
- [Examples](#examples)
- [License](#license)

## Installation

Make sure that python 3 and hatch are installed:

```
$ pkg install python3 py311-hatch
```

Run `hatch build` from the root of the repository.
Install it locally with:

```
$ pip install dist/bricoler-0.1.0-py3-none-any.whl
```

This will install it to `~/.local/bin`, so make sure that is in your PATH.

If you use bash and have `bash-completion` installed, this will also install a completion script to `~/.local/share/bash-completion/completions/bricoler`.
I find this very very useful.
If you use a different shell, please try adding a completion script for it and submit a PR.

## Examples

Run the FreeBSD regression test suite against an existing clone of the FreeBSD src tree:

```
$ bricoler freebsd-regression-test-suite --freebsd-src-git-checkout/url=/home/markj/sb/main/src --freebsd-src-build/kernel_config=GENERIC-KASAN
```

## License

`bricoler` is distributed under the terms of the [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) license.
