# orch

Orch is a program orchestration tool, inspired by expect(1) but scripted with
lua.  This utility allows scripted manipulation of programs for, e.g., testing
or automation purposes.  Orch drives spawn processes over a pts(4)
pseudo-terminal, which allows for a broader range of interactions with a program
under orchestration.

The authoritative source for this software is located at
https://git.kevans.dev/kevans/orch, but it's additionally mirrored to
[GitHub](https://github.com/kevans91/orch) for user-facing interactions.  Pull
requests and Issues are open on GitHub.

orch(1) strives to be portable.  Currently supported platforms:
 - FreeBSD
 - OpenBSD
 - NetBSD
 - macOS
 - Linux (tested on Ubuntu only)

## Notes for porting

We build on all of the above platforms.  To build and actually use orch, one
needs:

 - cmake
 - liblua + headers (orch(1) supports 5.2+)
 - a compiler
 - this source tree

CMake's built-in FindLua support will be used, but you may need to tweak the
following variables for install:

 - LUA_MODLIBDIR (default: /usr/local/lib/lua/MAJOR.MINOR) - path to install lua
    shared library modules
 - LUA_MODSHAREDIR (default: /usr/local/share/lua/MAJOR.MINOR) - path to install
    lua .lua modules
