/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <glob.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_glob(lua_State *L)
{
	const char *pattern;
	glob_t pglob;
	lua_Integer lflags;
	int flags, ret;

	pattern = luaL_checkstring(L, 1);
	lflags = luaL_optinteger(L, 2, 0);
	if (lflags < INT_MIN || lflags > INT_MAX) {
		return (luaL_error(L, "flags too large: %jx",
		    (uintmax_t)lflags));
	}
	flags = (int)lflags;

	/* For now we don't support errfunc, though that might be handy. */
	ret = glob(pattern, flags, NULL, &pglob);
	if (ret != 0) {
		lua_pushnil(L);
		lua_pushinteger(L, ret);
		return (2);
	}

	lua_newtable(L);
	for (size_t i = 0; i < pglob.gl_pathc; i++) {
		lua_pushstring(L, pglob.gl_pathv[i]);
		lua_rawseti(L, -2, i + 1);
	}
	globfree(&pglob);
	return (1);
}

static const struct luaL_Reg l_globtab[] = {
	{ "glob", l_glob },
	{ NULL, NULL }
};

int luaopen_glob(lua_State *L);

int
luaopen_glob(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_globtab, 0);
#define	ADDFLAG(c)		\
	lua_pushinteger(L, c);	\
	lua_setfield(L, -2, #c)
	/* Standard flags. */
	ADDFLAG(GLOB_APPEND);
	ADDFLAG(GLOB_DOOFFS);
	ADDFLAG(GLOB_ERR);
	ADDFLAG(GLOB_MARK);
	ADDFLAG(GLOB_NOCHECK);
	ADDFLAG(GLOB_NOESCAPE);
	ADDFLAG(GLOB_NOSORT);
	/* Nonstandard flags. */
	ADDFLAG(GLOB_ALTDIRFUNC);
	ADDFLAG(GLOB_BRACE);
	ADDFLAG(GLOB_MAGCHAR);
	ADDFLAG(GLOB_NOMAGIC);
	ADDFLAG(GLOB_TILDE);
	ADDFLAG(GLOB_LIMIT);
	/* Return values. */
	ADDFLAG(GLOB_ABORTED);
	ADDFLAG(GLOB_NOMATCH);
	ADDFLAG(GLOB_NOSPACE);
#undef ADDFLAG
	return (1);
}
