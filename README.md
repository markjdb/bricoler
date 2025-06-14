This is a utility for running FreeBSD src development workflows.  It is still
in its infancy and its interfaces will change.

The basic idea is to simplify common src development tasks by provding a light
framework to wrap operations like:
- building a FreeBSD src tree
- constructing a VM image from the output of a build
- booting the VM image (using QEMU or bhyve)
- running things in the guest once it has booted.

For example, to run the FreeBSD regression test suite against an existing clone
of the FreeBSD src tree, run:

```
$ bricoler run freebsd-src-regression-suite-run -p freebsd-src:url=/path/to/clone
```

Add "--show" to list the available parameters.  Run "bricoler run" without any
other arguments to list available tasks.

## Compatibility

This project only runs on FreeBSD.  It is written in Lua as part of an experiment
to try and build up a set of libraries exposing low-level interfaces in FreeBSD,
starting with system calls and eventually up to higher-level components like
pf, jails, bhyve, ZFS, etc..  This makes cross-platform support difficult.  If
it becomes tempting to run bricoler on other platforms, a rewrite in Python or
similar would likely be necessary.

## Building

It requires Lua 5.4 and cmake.

To build it, run "make" from the root directory.

## FreeBSD regression suite quickstart

On FreeBSD main, run the following:

```
$ git clone https://github.com/markjdb/bricoler
$ cd bricoler && make
```

If you run bash, try sourcing `bricoler-completion.bash`.
It auto-completes parameter names; I find it very very useful.

Then cd to the src dir you want to build and run the command below.
It assumes you are testing `main`, and that QEMU is installed.

```
$ cd /usr/src
$ bricoler run freebsd-src-regression-suite --param freebsd-src:url=$(pwd) --param freebsd-src:branch=main
```

Add `--show` to the end of that invocation to see all of the possible parameters.
For example, you can add `--param freebsd-src-build:clean=true` to request a clean build.

Specific tests can be chosen with freebsd-src-regression-suite:tests:

```
$ bricoler run freebsd-src-regression-suite -p "freebsd-src-regression-suite:tests=sys/netpfil/pf sbin/pfctl"
```


Once the regression suite finishes, you can look at the results with:
```
$ bricoler run freebsd-src-regression-suite report
```

If the guest panics it is possible to attach kgdb and interactively debug with:

```
$ bricoler run freebsd-src-regression-suite gdb
```
