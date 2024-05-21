/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
l_mkstemp(lua_State *L)
{
	const char *template;
	char *name;
	int fd, *fdp;

	template = luaL_checkstring(L, 1);
	name = strdup(template);
	if (name == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	fd = mkstemp(name);
	if (fd == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		free(name);
		return (3);
	}

	fdp = lua_newuserdata(L, sizeof(int));
	*fdp = fd;
	luaL_getmetatable(L, FREEBSD_SYS_FD_REGISTRY_KEY);
	lua_setmetatable(L, -2);
	lua_pushstring(L, name);
	free(name);
	return (2);
}

static const struct luaL_Reg l_mktemptab[] = {
	{ "mkstemp", l_mkstemp },
	{ NULL, NULL },
};

int	luaopen_mktemp(lua_State *L);

int
luaopen_mktemp(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_mktemptab, 0);
	return (1);
}
