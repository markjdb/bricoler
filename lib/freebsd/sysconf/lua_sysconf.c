/*
 * SPDX-License-Identifier: BSD-2-Clause
 *
 * Copyright (c) Mark Johnston <markj@FreeBSD.org>
 */

#include <errno.h>
#include <string.h>
#include <unistd.h>

#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>

static int
l_sysconf(lua_State *L)
{
	lua_Integer lname;
	long value;

	lname = luaL_checkinteger(L, 1);
	if (lname < INT_MIN || lname > INT_MAX) {
		lua_pushnil(L);
		lua_pushstring(L, "argument out of range");
		return (2);
	}

	value = sysconf((int)lname);
	if (value == -1) {
		lua_pushnil(L);
		lua_pushstring(L, strerror(errno));
		lua_pushinteger(L, errno);
		return (3);
	}

	lua_pushinteger(L, value);
	return (1);
}

static const struct luaL_Reg l_sysconftab[] = {
	{ "sysconf", l_sysconf },
	{ NULL, NULL },
};

int	luaopen_sysconf(lua_State *L);

int
luaopen_sysconf(lua_State *L)
{
	lua_newtable(L);
	luaL_setfuncs(L, l_sysconftab, 0);
#define ADDVALUE(v) do {		\
	lua_pushinteger(L, v);		\
	lua_setfield(L, -2, #v);	\
} while (0)
	ADDVALUE(_SC_ARG_MAX);
	ADDVALUE(_SC_CHILD_MAX);
	ADDVALUE(_SC_CLK_TCK);
	ADDVALUE(_SC_IOV_MAX);
	ADDVALUE(_SC_NGROUPS_MAX);
	ADDVALUE(_SC_NPROCESSORS_CONF);
	ADDVALUE(_SC_NPROCESSORS_ONLN);
	ADDVALUE(_SC_OPEN_MAX);
	ADDVALUE(_SC_PAGESIZE);
	ADDVALUE(_SC_PAGE_SIZE);
	ADDVALUE(_SC_STREAM_MAX);
	ADDVALUE(_SC_TZNAME_MAX);
	ADDVALUE(_SC_JOB_CONTROL);
	ADDVALUE(_SC_SAVED_IDS);
	ADDVALUE(_SC_VERSION);
	ADDVALUE(_SC_BC_BASE_MAX);
	ADDVALUE(_SC_BC_DIM_MAX);
	ADDVALUE(_SC_BC_SCALE_MAX);
	ADDVALUE(_SC_BC_STRING_MAX);
	ADDVALUE(_SC_COLL_WEIGHTS_MAX);
	ADDVALUE(_SC_EXPR_NEST_MAX);
	ADDVALUE(_SC_LINE_MAX);
	ADDVALUE(_SC_RE_DUP_MAX);
	ADDVALUE(_SC_2_VERSION);
	ADDVALUE(_SC_2_C_BIND);
	ADDVALUE(_SC_2_C_DEV);
	ADDVALUE(_SC_2_CHAR_TERM);
	ADDVALUE(_SC_2_FORT_DEV);
	ADDVALUE(_SC_2_FORT_RUN);
	ADDVALUE(_SC_2_LOCALEDEF);
	ADDVALUE(_SC_2_SW_DEV);
	ADDVALUE(_SC_2_UPE);
	ADDVALUE(_SC_AIO_LISTIO_MAX);
	ADDVALUE(_SC_AIO_MAX);
	ADDVALUE(_SC_AIO_PRIO_DELTA_MAX);
	ADDVALUE(_SC_DELAYTIMER_MAX);
	ADDVALUE(_SC_MQ_OPEN_MAX);
	ADDVALUE(_SC_RTSIG_MAX);
	ADDVALUE(_SC_SEM_NSEMS_MAX);
	ADDVALUE(_SC_SEM_VALUE_MAX);
	ADDVALUE(_SC_SIGQUEUE_MAX);
	ADDVALUE(_SC_TIMER_MAX);
	ADDVALUE(_SC_GETGR_R_SIZE_MAX);
	ADDVALUE(_SC_GETPW_R_SIZE_MAX);
	ADDVALUE(_SC_HOST_NAME_MAX);
	ADDVALUE(_SC_LOGIN_NAME_MAX);
	ADDVALUE(_SC_THREAD_STACK_MIN);
	ADDVALUE(_SC_THREAD_THREADS_MAX);
	ADDVALUE(_SC_TTY_NAME_MAX);
	ADDVALUE(_SC_SYMLOOP_MAX);
	ADDVALUE(_SC_ATEXIT_MAX);
	ADDVALUE(_SC_XOPEN_VERSION);
	ADDVALUE(_SC_XOPEN_XCU_VERSION);
	ADDVALUE(_SC_CPUSET_SIZE);
	ADDVALUE(_SC_PHYS_PAGES);
#undef ADDVALUE
	return (1);
}
