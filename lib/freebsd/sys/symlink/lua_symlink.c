/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_symlink(lua_State *L)
{
	const char *target, *linkpath;
	int error;

	target = luaL_checkstring(L, 1);
	linkpath = luaL_checkstring(L, 2);

	error = symlink(target, linkpath);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_readlink(lua_State *L)
{
	const char *path;
	char buf[PATH_MAX];
	ssize_t len;

	path = luaL_checkstring(L, 1);

	len = readlink(path, buf, sizeof(buf));
	if (len == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushlstring(L, buf, len);
	return (1);
}

static const struct luaL_Reg l_symlinktab[] = {
	{ "symlink", l_symlink },
	{ "readlink", l_readlink },
	{ NULL, NULL },
};

int	luaopen_symlink(lua_State *L);

int
luaopen_symlink(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_symlinktab, 0);
	return (1);
}
