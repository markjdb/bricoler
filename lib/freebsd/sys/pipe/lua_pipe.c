/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
_l_pipe2(lua_State *L, int flags)
{
	int fds[2], *fdp;

	if (pipe2(fds, flags) == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	fdp = lua_newuserdata(L, sizeof(int));
	*fdp = fds[0];
	luaL_getmetatable(L, FREEBSD_SYS_FD_REGISTRY_KEY);
	lua_setmetatable(L, -2);
	fdp = lua_newuserdata(L, sizeof(int));
	*fdp = fds[1];
	luaL_getmetatable(L, FREEBSD_SYS_FD_REGISTRY_KEY);
	lua_setmetatable(L, -2);
	return (2);
}

static int
l_pipe(lua_State *L)
{
	return (_l_pipe2(L, 0));
}

static int
l_pipe2(lua_State *L)
{
	lua_Integer lflags;

	lflags = luaL_checkinteger(L, 1);
	if (lflags < INT_MIN || lflags > INT_MAX) {
		lua_pushnil(L);
		lua_pushstring(L, "argument out of range");
		return (2);
	}
	return (_l_pipe2(L, lflags));
}

static const struct luaL_Reg l_pipetab[] = {
	{ "pipe", l_pipe },
	{ "pipe2", l_pipe2 },
	{ NULL, NULL },
};

int	luaopen_pipe(lua_State *L);

int
luaopen_pipe(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_pipetab, 0);

	lua_pushinteger(L, O_CLOEXEC);
	lua_setfield(L, -2, "O_CLOEXEC");
	lua_pushinteger(L, O_NONBLOCK);
	lua_setfield(L, -2, "O_NONBLOCK");

	return (1);
}
