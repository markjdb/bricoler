-- SPDX-License-Identifier: BSD-2-Clause
--
-- Copyright (c) Mark Johnston <markj@FreeBSD.org>

local scriptdir = arg[0]:match("(.+)/[^/]+$")
local oldcpath = package.cpath
package.cpath = oldcpath .. ";" .. scriptdir .. "/lib/freebsd/sys/?/?.so" ..
                ";" .. scriptdir .. "/lib/freebsd/?/?.so" ..
                ";" .. scriptdir .. "/lib/freebsd/?.so"

-- Register some udata metatables in the registry.
require 'freebsd_meta'

local M = {
    access = require 'access',
    chdir = require 'chdir',
    execve = require 'execve',
    getcwd = require 'getcwd',
    getuid = require 'getuid',
    mkdir = require 'mkdir',
    open = require 'open',
    pipe = require 'pipe',
    poll = require 'poll',
    read = require 'read',
    socket = require 'socket',
    stat = require 'stat',
    sysctl = require 'sysctl',
    unlink = require 'unlink',
    wait = require 'wait',

    errno = require 'errno',
    getaddrinfo = require 'getaddrinfo',
    libgen = require 'libgen',
    mktemp = require 'mktemp',
    posix_spawn = require 'posix_spawn',
    sysconf = require 'sysconf',
    uname = require 'uname',
}

package.cpath = oldcpath

return M
