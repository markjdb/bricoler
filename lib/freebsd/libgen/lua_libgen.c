/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <libgen.h>
#include <stdlib.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_basename(lua_State *L)
{
	char *path;

	path = strdup(luaL_checkstring(L, 1));
	if (path == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushstring(L, basename(path));
	free(path);
	return (1);
}

static int
l_dirname(lua_State *L)
{
	char *path;

	path = strdup(luaL_checkstring(L, 1));
	if (path == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushstring(L, dirname(path));
	free(path);
	return (1);
}

static const struct luaL_Reg l_libgentab[] = {
	{ "basename", l_basename },
	{ "dirname", l_dirname },
	{ NULL, NULL }
};

int luaopen_libgen(lua_State *L);

int
luaopen_libgen(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_libgentab, 0);
	return (1);
}
