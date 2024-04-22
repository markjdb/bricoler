/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

/*
 * Wrappers for wait.h functions.
 *
 * Currently only waitpid(2) is supported.
 */

#include <sys/wait.h>

#include <assert.h>
#include <errno.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_waitpid(lua_State *L)
{
	int error, options, status;
	pid_t pid;

	pid = luaL_checkinteger(L, 1);
	options = luaL_optinteger(L, 2, 0);

	error = waitpid(pid, &status, options);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	} else if (error == 0) {
		/* WNOHANG was specified. */
		lua_pushinteger(L, error);
		lua_pushstring(L, "running");
		return (2);
	} else {
		lua_pushinteger(L, error);
		if (WIFEXITED(status)) {
			lua_pushstring(L, "exited");
			lua_pushinteger(L, WEXITSTATUS(status));
		} else if (WIFSIGNALED(status)) {
			lua_pushstring(L, "signaled");
			lua_pushinteger(L, WTERMSIG(status));
		} else if (WIFSTOPPED(status)) {
			lua_pushstring(L, "stopped");
			lua_pushinteger(L, WSTOPSIG(status));
		} else {
			assert(0);
		}
		return (3);
	}
}

static const struct luaL_Reg l_waittab[] = {
	{ "waitpid", l_waitpid },
	{ NULL, NULL }
};

int luaopen_wait(lua_State *L);

int
luaopen_wait(lua_State *L)
{
	lua_newtable(L);

	luaL_setfuncs(L, l_waittab, 0);
#define	ADDFLAG(c)		\
	lua_pushinteger(L, c);	\
	lua_setfield(L, -2, #c)
	ADDFLAG(WNOHANG);
	ADDFLAG(WUNTRACED);
	ADDFLAG(WTRAPPED);
	ADDFLAG(WEXITED);
	ADDFLAG(WSTOPPED);
	ADDFLAG(WNOWAIT);
#undef ADDFLAG

	return (1);
}
