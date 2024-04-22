/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <assert.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

#include <stdio.h>

static int
l_close(lua_State *L)
{
	int error, *fdp;

	fdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	assert(*fdp != -1);
	error = close(*fdp);
	if (error == -1) {
		printf("%s:%d\n", __func__, __LINE__);
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}
	*fdp = -1;
	lua_pushboolean(L, 1);
	return (1);
}

static const luaL_Reg l_opentab[] = {
	{ "close", l_close },
	{ NULL, NULL },
};

int	luaopen_open(lua_State *L);

int
luaopen_open(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_opentab, 0);
	return (1);
}
