# Copyright (c) 2022 Mark Johnston <markj@FreeBSD.org>

# Common definitions for all shell-based tests.

export PATH=$(atf_get_srcdir)/..:${PATH}
export LUA_PATH_5_4=";;$(atf_get_srcdir)/../?.lua"
export LUA_CPATH_5_4=";;$(atf_get_srcdir)/../lib/freebsd/sys/?/?.so"
export BRICOLER_TASKDIR=$(atf_get_srcdir)/tasks
export BRICOLER_WORKDIR=$(pwd)/bricoler
