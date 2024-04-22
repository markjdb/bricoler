/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
l_unlink(lua_State *L)
{
	const char *path;
	int error;

	path = luaL_checkstring(L, 1);

	error = unlink(path);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushinteger(L, 0);
	return (1);
}

static int
l_unlinkat(lua_State *L)
{
	const char *path;
	int *dfdp, error, flags;

	dfdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	assert(*dfdp != -1);
	path = luaL_checkstring(L, 2);
	flags = luaL_optinteger(L, 3, 0);

	error = unlinkat(*dfdp, path, flags);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushinteger(L, 0);
	return (1);
}

static const struct luaL_Reg l_unlinktab[] = {
	{ "unlink", l_unlink },
	{ "unlinkat", l_unlinkat },
	{ NULL, NULL },
};

int	luaopen_unlink(lua_State *L);

int
luaopen_unlink(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_unlinktab, 0);
#define ADDFLAG(v) do {			\
	lua_pushinteger(L, v);		\
	lua_setfield(L, -2, #v);	\
} while (0)
	ADDFLAG(AT_REMOVEDIR);
	ADDFLAG(AT_RESOLVE_BENEATH);
#undef ADDFLAG
	return (1);
}
