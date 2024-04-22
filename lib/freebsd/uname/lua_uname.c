/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <sys/utsname.h>

#include <errno.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_uname(lua_State *L)
{
	struct utsname name;
	int error;

	luaL_argcheck(L, lua_gettop(L) == 0, 1, "too many arguments");

	error = uname(&name);
	if (error != 0) {
		error = errno;
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_newtable(L);
#define ADDFIELD(f) do {		\
	lua_pushstring(L, name.f);	\
	lua_setfield(L, -2, #f);	\
} while (0)
	ADDFIELD(sysname);
	ADDFIELD(nodename);
	ADDFIELD(release);
	ADDFIELD(version);
	ADDFIELD(machine);
#undef ADDFIELD

	return (1);
}

static const struct luaL_Reg l_unametab[] = {
	{ "uname", l_uname },
	{ NULL, NULL },
};

int	luaopen_uname(lua_State *L);

int
luaopen_uname(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_unametab, 0);
	return (1);
}
