/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <assert.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
l_freebsd_sys_fd_gc(lua_State *L)
{
	int error, *fdp;

	fdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	if (*fdp != -1) {
		error = close(*fdp);
		assert(error == 0);
		*fdp = -1;
	}
	return (0);
}

static const struct luaL_Reg l_freebsd_sys_fd[] = {
	{ "__gc", l_freebsd_sys_fd_gc },
	{ NULL, NULL },
};

int	luaopen_freebsd_meta(lua_State *L);

int
luaopen_freebsd_meta(lua_State *L)
{
	int ret;

	ret = luaL_newmetatable(L, FREEBSD_SYS_FD_REGISTRY_KEY);
	assert(ret == 1);
	luaL_setfuncs(L, l_freebsd_sys_fd, 0);

	lua_newtable(L);

	return (1);
}
