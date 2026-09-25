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
- [Usage](#usage)
- [License](#license)

## Installation

```sh
pkg install bricoler
```

There is a bricoler man page, so you can run `man bricoler` to get usage information and examples.

bricoler ships with a completion script for bash.
I find this very very useful.
If you use a different shell, please try adding a completion script for it and submit a PR.

Installing ccache is recommended, it will be used automatically.

### Installation From Source

Make sure that Python 3, hatch and other dependencies are installed:

```sh
py="py$(pkg rall-depends python3 | sed -e s/^python// -e 's/-.*$//')"
pkg install python3 "$py-hatch" "$py-pip" "$py-sqlite3"
```

Use hatch to build bricoler:

```sh
hatch build
````

Install bricoler locally with:

```sh
pip install dist/bricoler-*.whl
```

This will install it to the `~/.local` prefix, so make sure that `~/.local/bin` is in your PATH.

## Usage

Example:

```sh
bricoler freebsd-regression-test-suite \
    --freebsd-regression-test-suite/memory=8192 \
    --freebsd-regression-test-suite/ncpus=8 \
    --freebsd-regression-test-suite/tests="sys/netpfil/pf sbin/pfctl" \
    --freebsd-src-git-checkout/url=/usr/src \
    --freebsd-src-build/kernel_config=GENERIC-KASAN
```

More extensive usage information can be found in the man page `man share/bricoler.1`.

## License

`bricoler` is distributed under the terms of the [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) license.
