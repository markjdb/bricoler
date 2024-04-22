/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

/*
 * Wrappers for posix_spawn(3) and friends.
 *
 * posix_spawn() and posix_spawnp() return a PID upon success, otherwise: nil,
 * an error message, an error number.
 *
 * If the second parameter is a udata created by
 * posix_spawn_file_actions_init(), the file actions are used for the spawn,
 * otherwise the second parameter should be an array of command-line parameters.
 *
 * Spawn attribute support is not yet implemented.
 *
 * Example:
 *
 *   posix_spawn("ls", { "ls", "-l", "/tmp" }, { "TERM=xterm", "CLICOLOR=1" })
 */

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <spawn.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

#include <lua_freebsd_meta.h>

#define	POSIX_SPAWN_FILE_ACTIONS_KEY	"freebsd_posix_spawn_file_actions"
#define	POSIX_SPAWNATTR_KEY		"freebsd_posix_spawnattr"

extern char **environ;

static int
l_posix_spawn1(lua_State *L, bool path)
{
	posix_spawn_file_actions_t file_actions, *file_actionsp;
	posix_spawnattr_t attr;
	const char *file;
	const char **argv;
	const char **envp;
	char *const *_argv;
	char *const *_envp;
	int argi, argc, envc, ret, ret1;
	pid_t pid;

	ret = posix_spawnattr_init(&attr);
	if (ret != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(ret));
		lua_pushinteger(L, ret);
		return (3);
	}

	argi = 1;
	file = luaL_checkstring(L, argi++);

	if (lua_type(L, argi) == LUA_TUSERDATA) {
		luaL_checkudata(L, argi, POSIX_SPAWN_FILE_ACTIONS_KEY);
		file_actionsp = lua_touserdata(L, argi++);
	} else {
		luaL_checktype(L, argi, LUA_TTABLE);
		file_actionsp = &file_actions;
		ret = posix_spawn_file_actions_init(file_actionsp);
		if (ret != 0) {
			lua_pushnil(L);
			lua_pushstring(L, strerror(ret));
			lua_pushinteger(L, ret);
			return (3);
		}
	}

	argc = lua_rawlen(L, argi);
	argv = calloc(argc + 1, sizeof(char *));
	if (argv == NULL) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}
	for (int i = 0; i < argc; i++) {
		lua_rawgeti(L, argi, i + 1);
		argv[i] = lua_tostring(L, -1);
		lua_pop(L, 1);
	}
	argi++;

	/*
	 * POSIX doesn't appear to specify what happens if the envp is NULL.
	 * FreeBSD treats it as meaning that the environment is to be inherited,
	 * which seems sensible.  Follow that behaviour if the caller didn't
	 * specify a final parameter.
	 */
	if (lua_gettop(L) >= argi && lua_type(L, argi) != LUA_TNIL) {
		luaL_checktype(L, argi, LUA_TTABLE);
		envc = lua_rawlen(L, argi);
		envp = calloc(envc + 1, sizeof(char *));
		if (envp == NULL) {
			lua_pushnil(L);
			lua_pushstring(L, strerror(errno));
			lua_pushinteger(L, errno);
			return (3);
		}
		for (int i = 0; i < envc; i++) {
			lua_rawgeti(L, argi, i + 1);
			envp[i] = lua_tostring(L, -1);
			lua_pop(L, 1);
		}
		argi++;
	} else {
		envp = __DECONST(const char **, environ);
	}

	_argv = __DECONST(char * const *, argv);
	_envp = __DECONST(char * const *, envp);
	ret = path ?
	    posix_spawnp(&pid, file, file_actionsp, &attr, _argv, _envp) :
	    posix_spawn(&pid, file, file_actionsp, &attr, _argv, _envp);

	if (file_actionsp == &file_actions) {
		ret1 = posix_spawn_file_actions_destroy(file_actionsp);
		assert(ret1 == 0);
	}
	ret1 = posix_spawnattr_destroy(&attr);
	assert(ret1 == 0);

	free(argv);
	if (envp != __DECONST(const char **, environ))
		free(envp);

	if (ret != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(ret));
		lua_pushinteger(L, ret);
		return (3);
	}

	lua_pushinteger(L, pid);
	return (1);
}

static int
l_posix_spawn(lua_State *L)
{
	return (l_posix_spawn1(L, false));
}

static int
l_posix_spawnp(lua_State *L)
{
	return (l_posix_spawn1(L, true));
}

static int
l_posix_spawn_file_actions_init(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	int ret;

	file_actions = lua_newuserdata(L, sizeof(posix_spawn_file_actions_t));
	ret = posix_spawn_file_actions_init(file_actions);
	if (ret != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(ret));
		lua_pushinteger(L, ret);
		return (3);
	}

	luaL_getmetatable(L, POSIX_SPAWN_FILE_ACTIONS_KEY);
	lua_setmetatable(L, -2);

	return (1);
}

static int
l_posix_spawn_file_actions_addopen(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	const char *path;
	int error, *fdp, oflags;
	mode_t mode;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	fdp = luaL_checkudata(L, 2, FREEBSD_SYS_FD_REGISTRY_KEY);
	path = luaL_checkstring(L, 3);
	oflags = luaL_checkinteger(L, 4);
	mode = luaL_optinteger(L, 5, 0);

	assert(fcntl(*fdp, F_GETFD) != -1);

	error = posix_spawn_file_actions_addopen(file_actions, *fdp, path,
	    oflags, mode);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawn_file_actions_adddup2(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	int error, *oldfdp, newfd;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	oldfdp = luaL_checkudata(L, 2, FREEBSD_SYS_FD_REGISTRY_KEY);
	newfd = luaL_checkinteger(L, 3);

	assert(fcntl(*oldfdp, F_GETFD) != -1);

	error = posix_spawn_file_actions_adddup2(file_actions, *oldfdp, newfd);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawn_file_actions_addclose(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	int error, *fdp;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	fdp = luaL_checkudata(L, 2, FREEBSD_SYS_FD_REGISTRY_KEY);

	assert(fcntl(*fdp, F_GETFD) != -1);

	error = posix_spawn_file_actions_addclose(file_actions, *fdp);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}


static int
l_posix_spawn_file_actions_addclosefrom_np(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	int error, from;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	from = luaL_checkinteger(L, 2);

	error = posix_spawn_file_actions_addclosefrom_np(file_actions, from);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawn_file_actions_addchdir_np(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	const char *path;
	int error;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	path = luaL_checkstring(L, 2);

	error = posix_spawn_file_actions_addchdir_np(file_actions, path);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawn_file_actions_addfchdir_np(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;
	int error, *fdp;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	fdp = luaL_checkudata(L, 2, FREEBSD_SYS_FD_REGISTRY_KEY);

	assert(fcntl(*fdp, F_GETFD) != -1);

	error = posix_spawn_file_actions_addfchdir_np(file_actions, *fdp);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawnattr_init(lua_State *L)
{
	posix_spawnattr_t *attr;
	int error;

	attr = lua_newuserdata(L, sizeof(posix_spawnattr_t));

	error = posix_spawnattr_init(attr);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	luaL_getmetatable(L, POSIX_SPAWNATTR_KEY);
	lua_setmetatable(L, -2);
	return (1);
}

static int
l_posix_spawnattr_getflags(lua_State *L)
{
	posix_spawnattr_t *attr;
	short flags;
	int error;

	attr = luaL_checkudata(L, 1, POSIX_SPAWNATTR_KEY);

	error = posix_spawnattr_getflags(attr, &flags);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushinteger(L, flags);
	return (1);
}

static int
l_posix_spawnattr_setflags(lua_State *L)
{
	posix_spawnattr_t *attr;
	lua_Integer lflags;
	short flags;
	int error;

	attr = luaL_checkudata(L, 1, POSIX_SPAWNATTR_KEY);
	lflags = luaL_checkinteger(L, 2);
	if (lflags > SHRT_MAX || lflags < SHRT_MIN) {
		return (luaL_error(L, "flags too large: %jx",
		    (uintmax_t)lflags));
	}
	flags = (short)lflags;

	error = posix_spawnattr_setflags(attr, flags);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
l_posix_spawnattr_getpgroup(lua_State *L)
{
	posix_spawnattr_t *attr;
	pid_t pgroup;
	int error;

	attr = luaL_checkudata(L, 1, POSIX_SPAWNATTR_KEY);

	error = posix_spawnattr_getpgroup(attr, &pgroup);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushinteger(L, pgroup);
	return (1);
}

static int
l_posix_spawnattr_setpgroup(lua_State *L)
{
	posix_spawnattr_t *attr;
	lua_Integer lpgrp;
	pid_t pgrp;
	int error;

	attr = luaL_checkudata(L, 1, POSIX_SPAWNATTR_KEY);
	lpgrp = luaL_checkinteger(L, 2);
	if (lpgrp > INT_MAX || lpgrp < INT_MIN)
		return (luaL_error(L, "pgrp too large: %jd", (intmax_t)lpgrp));
	pgrp = (pid_t)lpgrp;

	error = posix_spawnattr_setpgroup(attr, pgrp);
	if (error != 0) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(error));
		lua_pushinteger(L, error);
		return (3);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static const struct luaL_Reg l_posix_spawntab[] = {
	{ "posix_spawn", l_posix_spawn },
	{ "posix_spawnp", l_posix_spawnp },

	{ "posix_spawn_file_actions_init",
	    l_posix_spawn_file_actions_init },
	{ "posix_spawn_file_actions_addopen",
	    l_posix_spawn_file_actions_addopen },
	{ "posix_spawn_file_actions_adddup2",
	    l_posix_spawn_file_actions_adddup2 },
	{ "posix_spawn_file_actions_addclose",
	    l_posix_spawn_file_actions_addclose },
	{ "posix_spawn_file_actions_addclosefrom_np",
	    l_posix_spawn_file_actions_addclosefrom_np },
	{ "posix_spawn_file_actions_addchdir_np",
	    l_posix_spawn_file_actions_addchdir_np },
	{ "posix_spawn_file_actions_addfchdir_np",
	    l_posix_spawn_file_actions_addfchdir_np },

	{ "posix_spawnattr_init", l_posix_spawnattr_init },
	{ "posix_spawnattr_getflags", l_posix_spawnattr_getflags },
	{ "posix_spawnattr_setflags", l_posix_spawnattr_setflags },
	{ "posix_spawnattr_getpgroup", l_posix_spawnattr_getpgroup },
	{ "posix_spawnattr_setpgroup", l_posix_spawnattr_setpgroup },
#ifdef notyet
	{ "posix_spawnattr_getsigdefault", l_posix_spawnattr_getsigdefault },
	{ "posix_spawnattr_setsigdefault", l_posix_spawnattr_setsigdefault },
	{ "posix_spawnattr_getsigmask", l_posix_spawnattr_getsigmask },
	{ "posix_spawnattr_setsigmask", l_posix_spawnattr_setsigmask },
	{ "posix_spawnattr_getschedparam", l_posix_spawnattr_getschedparam },
	{ "posix_spawnattr_setschedparam", l_posix_spawnattr_setschedparam },
	{ "posix_spawnattr_getschedpolicy", l_posix_spawnattr_getschedpolicy },
	{ "posix_spawnattr_setschedpolicy", l_posix_spawnattr_setschedpolicy },
#endif

	{ NULL, NULL }
};

static int
l_posix_spawn_file_actions_destroy(lua_State *L)
{
	posix_spawn_file_actions_t *file_actions;

	file_actions = luaL_checkudata(L, 1, POSIX_SPAWN_FILE_ACTIONS_KEY);
	posix_spawn_file_actions_destroy(file_actions);
	return (0);
}

static const struct luaL_Reg l_posix_spawn_file_actions_mt[] = {
	{ "__gc", l_posix_spawn_file_actions_destroy },
	{ NULL, NULL }
};

static int
l_posix_spawnattr_destroy(lua_State *L)
{
	posix_spawnattr_t *attr;

	attr = luaL_checkudata(L, 1, POSIX_SPAWNATTR_KEY);
	posix_spawnattr_destroy(attr);
	return (0);
}

static const struct luaL_Reg l_posix_spawnattr_mt[] = {
	{ "__gc", l_posix_spawnattr_destroy },
	{ NULL, NULL }
};

int	luaopen_posix_spawn(lua_State *L);

int
luaopen_posix_spawn(lua_State *L)
{
	int ret;

	ret = luaL_newmetatable(L, POSIX_SPAWN_FILE_ACTIONS_KEY);
	assert(ret == 1);
	luaL_setfuncs(L, l_posix_spawn_file_actions_mt, 0);
	ret = luaL_newmetatable(L, POSIX_SPAWNATTR_KEY);
	assert(ret == 1);
	luaL_setfuncs(L, l_posix_spawnattr_mt, 0);

	lua_newtable(L);
	luaL_setfuncs(L, l_posix_spawntab, 0);
#define	ADDFLAG(c)		\
	lua_pushinteger(L, c);	\
	lua_setfield(L, -2, #c)
	ADDFLAG(POSIX_SPAWN_RESETIDS);
	ADDFLAG(POSIX_SPAWN_SETPGROUP);
	ADDFLAG(POSIX_SPAWN_SETSIGDEF);
	ADDFLAG(POSIX_SPAWN_SETSIGMASK);
	ADDFLAG(POSIX_SPAWN_SETSCHEDPARAM);
	ADDFLAG(POSIX_SPAWN_SETSCHEDULER);
	ADDFLAG(POSIX_SPAWN_DISABLE_ASLR_NP);
#undef ADDFLAG

	return (1);
}
