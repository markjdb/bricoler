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
l_access1(lua_State *L, int (*fn)(const char *, int))

{
	const char *path;
	int mode, ret;

	path = luaL_checkstring(L, 1);
	mode = luaL_checkinteger(L, 2);

	ret = fn(path, mode);
	if (ret == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_access(lua_State *L)
{
	return (l_access1(L, access));
}

static int
l_eaccess(lua_State *L)
{
	return (l_access1(L, eaccess));
}

static const struct luaL_Reg l_accesstab[] = {
	{"access", l_access},
	{"eaccess", l_eaccess},
	{NULL, NULL},
};

int	luaopen_access(lua_State *L);

int
luaopen_access(lua_State *L)
{
	lua_newtable(L);

	luaL_setfuncs(L, l_accesstab, 0);

	lua_pushinteger(L, R_OK);
	lua_setfield(L, -2, "R_OK");
	lua_pushinteger(L, W_OK);
	lua_setfield(L, -2, "W_OK");
	lua_pushinteger(L, X_OK);
	lua_setfield(L, -2, "X_OK");

	return (1);
}
