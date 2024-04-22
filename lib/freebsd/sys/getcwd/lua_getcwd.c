/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_getcwd(lua_State *L)
{
	char buf[PATH_MAX];

	if (getcwd(buf, sizeof(buf)) == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushstring(L, buf);
	return (1);
}

static const struct luaL_Reg l_getcwdtab[] = {
	{ "getcwd", l_getcwd },
	{ NULL, NULL },
};

int	luaopen_getcwd(lua_State *L);

int
luaopen_getcwd(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_getcwdtab, 0);
	return (1);
}
