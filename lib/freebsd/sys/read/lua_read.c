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

#include <lua_freebsd_meta.h>

static int
l_read(lua_State *L)
{
	char *buf;
	ssize_t n;
	int *fdp;

	fdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	n = luaL_checkinteger(L, 2);
	buf = malloc(n);
	if (buf == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	n = read(*fdp, buf, n);
	if (n == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		free(buf);
		return (3);
	}

	lua_pushlstring(L, buf, n);
	free(buf);
	return (1);
}

static int
l_pread(lua_State *L)
{
	char *buf;
	off_t off;
	ssize_t n;
	int *fdp;

	fdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	n = luaL_checkinteger(L, 2);
	off = luaL_checkinteger(L, 3);
	buf = malloc(n);
	if (buf == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	n = pread(*fdp, buf, n, off);
	if (n == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		free(buf);
		return (3);
	}

	lua_pushlstring(L, buf, n);
	free(buf);
	return (1);
}

static const struct luaL_Reg l_readtab[] = {
	{ "read", l_read },
	{ "pread", l_pread },
	{ NULL, NULL },
};

int	luaopen_read(lua_State *L);

int
luaopen_read(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_readtab, 0);
	return (1);
}
