/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdlib.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

static int
l_poll(lua_State *L)
{
	struct pollfd *fds;
	int nfds, res, timeout;
	lua_Integer ltimeout;

	luaL_checktype(L, 1, LUA_TTABLE);
	nfds = lua_rawlen(L, 1);

	fds = calloc(nfds, sizeof(*fds));
	if (fds == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}
	for (int i = 0; i < nfds; i++) {
		lua_Integer events;
		int *fdp;

		lua_rawgeti(L, 1, i + 1);
		luaL_checktype(L, -1, LUA_TTABLE);
		lua_getfield(L, -1, "fd");
		fdp = luaL_checkudata(L, -1, FREEBSD_SYS_FD_REGISTRY_KEY);
		lua_pop(L, 1);
		lua_getfield(L, -1, "events");
		events = luaL_checkinteger(L, -1);
		lua_pop(L, 1);
		lua_pop(L, 1);

		if (events > SHRT_MAX || events < SHRT_MIN) {
			lua_pushnil(L);
			lua_pushstring(L, "events too large");
			lua_pushinteger(L, EINVAL);
			free(fds);
			return (3);
		}
		fds[i].fd = *fdp;
		fds[i].events = (short)events;
	}

	ltimeout = luaL_optinteger(L, 2, -1);
	if (ltimeout > INT_MAX) {
		lua_pushnil(L);
		lua_pushstring(L, "timeout too large");
		lua_pushinteger(L, EINVAL);
		return (3);
	}
	timeout = (int)ltimeout;

	res = poll(fds, nfds, timeout);
	if (res == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		free(fds);
		return (3);
	}

	for (int i = 0; i < nfds; i++) {
		lua_rawgeti(L, 1, i + 1);
		luaL_checktype(L, -1, LUA_TTABLE);
		lua_pushinteger(L, fds[i].revents);
		lua_setfield(L, -2, "revents");
	}
	free(fds);
	lua_pushinteger(L, res);
	return (1);
}

static const struct luaL_Reg l_polltab[] = {
	{ "poll", l_poll },
	{ NULL, NULL },
};

int	luaopen_poll(lua_State *L);

int
luaopen_poll(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_polltab, 0);
#define	ADDCONST(c) do {		\
	lua_pushinteger(L, c);		\
	lua_setfield(L, -2, #c);	\
} while (0)
	ADDCONST(POLLIN);
	ADDCONST(POLLOUT);
	ADDCONST(POLLRDNORM);
	ADDCONST(POLLRDBAND);
	ADDCONST(POLLWRNORM);
	ADDCONST(POLLWRBAND);
	ADDCONST(POLLERR);
	ADDCONST(POLLHUP);
	ADDCONST(POLLRDHUP);
	ADDCONST(POLLNVAL);
#undef ADDCONST
	return (1);
}
