/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <sys/socket.h>

#include <errno.h>
#include <limits.h>
#include <netdb.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
get_int_field(lua_State *L, const char *name, int *valp)
{
	lua_Integer lval;

	lua_getfield(L, 3, name);
	lval = luaL_optinteger(L, -1, 0);
	if (lval < INT_MIN || lval > INT_MAX) {
		lua_pushnil(L);
		lua_pushfstring(L, "%s too large", name);
		lua_pushinteger(L, EINVAL);
		return (3);
	}
	*valp = lval;
	return (0);
}

static int
l_getaddrinfo(lua_State *L)
{
	const char *hostname, *servname;
	struct addrinfo *ai, hints, *res;
	int error, i;

	hostname = luaL_checkstring(L, 1);
	if (strcmp(hostname, "") == 0)
		hostname = NULL;
	servname = luaL_checkstring(L, 2);
	if (strcmp(servname, "") == 0)
		servname = NULL;

	/* Let the caller optionally pass a table of hints. */
	memset(&hints, 0, sizeof(hints));
	if (!lua_isnoneornil(L, 3)) {
		luaL_checktype(L, 3, LUA_TTABLE);
		error = get_int_field(L, "flags", &hints.ai_flags);
		if (error != 0)
			return (error);
		error = get_int_field(L, "family", &hints.ai_family);
		if (error != 0)
			return (error);
		error = get_int_field(L, "socktype", &hints.ai_socktype);
		if (error != 0)
			return (error);
		error = get_int_field(L, "protocol", &hints.ai_protocol);
		if (error != 0)
			return (error);
	}

	error = getaddrinfo(hostname, servname, &hints, &res);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, gai_strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	/* Convert the linked list of results into an array of tables. */
	lua_newtable(L);
	for (ai = res, i = 1; ai != NULL; ai = ai->ai_next, i++) {
		lua_pushnumber(L, i);
		lua_newtable(L);
		lua_pushstring(L, "flags");
		lua_pushinteger(L, ai->ai_flags);
		lua_settable(L, -3);
		lua_pushstring(L, "family");
		lua_pushinteger(L, ai->ai_family);
		lua_settable(L, -3);
		lua_pushstring(L, "socktype");
		lua_pushinteger(L, ai->ai_socktype);
		lua_settable(L, -3);
		lua_pushstring(L, "protocol");
		lua_pushinteger(L, ai->ai_protocol);
		lua_settable(L, -3);
		lua_pushstring(L, "addrlen");
		lua_pushinteger(L, ai->ai_addrlen);
		lua_settable(L, -3);
		lua_pushstring(L, "addr");
		lua_pushlstring(L, (const char *)ai->ai_addr, ai->ai_addrlen);
		lua_settable(L, -3);
		if (ai->ai_canonname != NULL) {
			lua_pushstring(L, "canonname");
			lua_pushstring(L, ai->ai_canonname);
			lua_settable(L, -3);
		}

		lua_settable(L, -3);
	}
	freeaddrinfo(res);
	return (1);
}

static const luaL_Reg l_getaddrinfotab[] = {
	{ "getaddrinfo", l_getaddrinfo },
	{ NULL, NULL }
};

int	luaopen_getaddrinfo(lua_State *L);

int
luaopen_getaddrinfo(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_getaddrinfotab, 0);
#define	ADDCONST(c) do {		\
	lua_pushinteger(L, c);		\
	lua_setfield(L, -2, #c);	\
} while (0)
	ADDCONST(AI_ADDRCONFIG);
	ADDCONST(AI_ALL);
	ADDCONST(AI_CANONNAME);
	ADDCONST(AI_NUMERICHOST);
	ADDCONST(AI_NUMERICSERV);
	ADDCONST(AI_PASSIVE);
	ADDCONST(AI_V4MAPPED);
#undef ADDCONST
	return (1);
}
