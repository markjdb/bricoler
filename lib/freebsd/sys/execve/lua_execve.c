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
l_execve(lua_State *L)
{
	const char *cmd;
	char **argv, **envp;
	unsigned int argc, envc;
	int error;

	argv = envp = NULL;

	luaL_argcheck(L, lua_type(L, 1) == LUA_TSTRING, 1,
	    "bad argument type, expected a string");
	luaL_argcheck(L, lua_type(L, 2) == LUA_TTABLE, 1,
	    "bad argument type, expected a table");
	luaL_argcheck(L, lua_type(L, 3) == LUA_TTABLE, 1,
	    "bad argument type, expected a table");

	cmd = lua_tostring(L, 1);

	lua_pushnil(L);
	for (argc = 0; lua_next(L, 2); argc++)
		lua_pop(L, 1);
	lua_pushnil(L);
	for (envc = 0; lua_next(L, 3); envc++)
		lua_pop(L, 1);

	argv = calloc(argc + 1, sizeof(char *));
	if (argv == NULL)
		goto error;
	envp = calloc(envc + 1, sizeof(char *));
	if (envp == NULL)
		goto error;

	lua_pushnil(L);
	for (size_t i = 0; lua_next(L, 2) != 0; i++) {
		argv[i] = __DECONST(char *, lua_tostring(L, -1));
		lua_pop(L, 1);
	}
	lua_pushnil(L);
	for (size_t i = 0; lua_next(L, 3) != 0; i++) {
		envp[i] = __DECONST(char *, lua_tostring(L, -1));
		lua_pop(L, 1);
	}

	(void)execve(cmd, argv, envp);

error:
	error = errno;
	free(argv);
	free(envp);

	lua_pushnil(L);
	lua_pushstring(L, strerror(error));
	lua_pushinteger(L, error);

	return (3);
}

static int
l_fexecve(lua_State *L)
{
	int error;

	lua_pushnil(L);
	error = ENOSYS;
	lua_pushstring(L, strerror(error));
	lua_pushinteger(L, error);

	return (3);
}

static const struct luaL_Reg l_execvetab[] = {
	{"execve", l_execve},
	{"fexecve", l_fexecve},
	{NULL, NULL},
};

int	luaopen_execve(lua_State *L);

int
luaopen_execve(lua_State *L)
{
	lua_newtable(L);

	luaL_setfuncs(L, l_execvetab, 0);

	return (1);
}
