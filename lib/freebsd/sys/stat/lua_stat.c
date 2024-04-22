/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <sys/stat.h>

#include <errno.h>
#include <string.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_stat1(lua_State *L, int (*fn)(const char *, struct stat *))
{
	const char *path;
	struct stat sb;
	int error;

	path = luaL_checkstring(L, 1);

	error = fn(path, &sb);
	if (error == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_newtable(L);
#define	SETFIELD(name) do {			\
	lua_pushstring(L, #name);		\
	lua_pushinteger(L, sb.st_##name);	\
	lua_settable(L, -3);			\
} while (0)
	SETFIELD(dev);
	SETFIELD(ino);
	SETFIELD(mode);
	SETFIELD(nlink);
	SETFIELD(uid);
	SETFIELD(gid);
	SETFIELD(rdev);
	SETFIELD(size);
	SETFIELD(blocks);
	SETFIELD(blksize);
#undef SETFIELD
	return (1);
}

static int
l_stat(lua_State *L)
{
	return (l_stat1(L, stat));
}

static int
l_fstat(lua_State *L)
{
	return (l_stat1(L, lstat));
}

#define	l_S_PRED(name)						\
static int							\
l_S_##name(lua_State *L)					\
{								\
	lua_pushboolean(L, S_##name(luaL_checkinteger(L, 1)));	\
	return (1);						\
}
l_S_PRED(ISBLK)
l_S_PRED(ISCHR)
l_S_PRED(ISDIR)
l_S_PRED(ISFIFO)
l_S_PRED(ISREG)
l_S_PRED(ISLNK)
l_S_PRED(ISSOCK)
#undef l_S_PRED

static const struct luaL_Reg l_stattab[] = {
	{ "stat", l_stat },
	{ "lstat", l_fstat },

	{ "S_ISBLK", l_S_ISBLK },
	{ "S_ISCHR", l_S_ISCHR },
	{ "S_ISDIR", l_S_ISDIR },
	{ "S_ISFIFO", l_S_ISFIFO },
	{ "S_ISREG", l_S_ISREG },
	{ "S_ISLNK", l_S_ISLNK },
	{ "S_ISSOCK", l_S_ISSOCK },
	{ NULL, NULL },
};

int	luaopen_stat(lua_State *L);

int
luaopen_stat(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_stattab, 0);
#define	ADDFLAG(c) do {			\
	lua_pushinteger(L, c);		\
	lua_setfield(L, -2, #c);	\
} while (0)
	ADDFLAG(S_IFMT);
	ADDFLAG(S_IFIFO);
	ADDFLAG(S_IFCHR);
	ADDFLAG(S_IFDIR);
	ADDFLAG(S_IFBLK);
	ADDFLAG(S_IFREG);
	ADDFLAG(S_IFLNK);
	ADDFLAG(S_IFSOCK);
	ADDFLAG(S_IFWHT);
	ADDFLAG(S_ISUID);
	ADDFLAG(S_ISGID);
	ADDFLAG(S_ISVTX);
	ADDFLAG(S_IRWXU);
	ADDFLAG(S_IRUSR);
	ADDFLAG(S_IWUSR);
	ADDFLAG(S_IXUSR);
	ADDFLAG(S_IRWXG);
	ADDFLAG(S_IRGRP);
	ADDFLAG(S_IWGRP);
	ADDFLAG(S_IXGRP);
	ADDFLAG(S_IRWXO);
	ADDFLAG(S_IROTH);
	ADDFLAG(S_IWOTH);
	ADDFLAG(S_IXOTH);
#undef ADDFLAG
	return (1);
}
