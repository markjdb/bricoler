/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <sys/socket.h>

#include <errno.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
l_socket(lua_State *L)
{
	int domain, type, protocol;
	int fd, *fdp;

	domain = luaL_checkinteger(L, 1);
	type = luaL_checkinteger(L, 2);
	protocol = luaL_optinteger(L, 3, 0);

	fd = socket(domain, type, protocol);
	if (fd == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	fdp = lua_newuserdata(L, sizeof(int));
	*fdp = fd;
	luaL_getmetatable(L, FREEBSD_SYS_FD_REGISTRY_KEY);
	lua_setmetatable(L, -2);
	return (1);
}

static int
l_bind(lua_State *L)
{
	const struct sockaddr_storage *ss;
	size_t sslen;
	int error, fd, *fdp;

	fdp = luaL_checkudata(L, 1, FREEBSD_SYS_FD_REGISTRY_KEY);
	fd = *fdp;
	ss = (const void *)luaL_checklstring(L, 2, &sslen);

	error = bind(fd, (const struct sockaddr *)ss, sslen);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}
	lua_pushboolean(L, 1);
	return (1);
}

static const struct luaL_Reg l_sockettab[] = {
	{ "socket", l_socket },
	{ "bind", l_bind },
	{ NULL, NULL }
};

int luaopen_socket(lua_State *L);

int
luaopen_socket(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_sockettab, 0);
#define	ADDCONST(c) do {		\
	lua_pushinteger(L, c);		\
	lua_setfield(L, -2, #c);	\
} while (0)
	ADDCONST(PF_LOCAL);
	ADDCONST(PF_INET);
	ADDCONST(PF_INET6);
	ADDCONST(SOCK_STREAM);
	ADDCONST(SOCK_DGRAM);
	ADDCONST(SOCK_RAW);
	ADDCONST(SOCK_SEQPACKET);
	ADDCONST(SOCK_CLOEXEC);
	ADDCONST(SOCK_NONBLOCK);
#undef ADDCONST
	return (1);
}
