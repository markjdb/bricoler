/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_getuid(lua_State *L)
{
	lua_pushinteger(L, getuid());
	return (1);
}

static int
l_geteuid(lua_State *L)
{
	lua_pushinteger(L, geteuid());
	return (1);
}

static int
l_getgid(lua_State *L)
{
	lua_pushinteger(L, getgid());
	return (1);
}

static int
l_getegid(lua_State *L)
{
	lua_pushinteger(L, getegid());
	return (1);
}

static int
l_issetugid(lua_State *L)
{
	lua_pushboolean(L, issetugid() != 0);
	return (1);
}

static const struct luaL_Reg l_getuidtab[] = {
	{ "getuid", l_getuid },
	{ "geteuid", l_geteuid },
	{ "getgid", l_getgid },
	{ "getegid", l_getegid },
	{ "issetugid", l_issetugid },
	{ NULL, NULL },
};

int	luaopen_getuid(lua_State *L);

int
luaopen_getuid(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_getuidtab, 0);
	return (1);
}
