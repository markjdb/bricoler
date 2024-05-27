/*-
 * Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

#include "orch.h"
#include "orch_lib.h"

#include <lua.h>
#include <lauxlib.h>

#define	ORCHLUA_TERMHANDLE	"orch_term"

#define	CNTRL_ENTRY(c, m)	{ c, #c, m }
const struct orchlua_tty_cntrl orchlua_cntrl_chars[] = {
	CNTRL_ENTRY(VEOF,	CNTRL_CANON),
	CNTRL_ENTRY(VEOL,	CNTRL_CANON),
	CNTRL_ENTRY(VERASE,	CNTRL_CANON),
	CNTRL_ENTRY(VINTR,	CNTRL_BOTH),
	CNTRL_ENTRY(VKILL,	CNTRL_CANON),
	CNTRL_ENTRY(VMIN,	CNTRL_NCANON | CNTRL_LITERAL),
	CNTRL_ENTRY(VQUIT,	CNTRL_BOTH),
	CNTRL_ENTRY(VSUSP,	CNTRL_BOTH),
	CNTRL_ENTRY(VTIME,	CNTRL_NCANON | CNTRL_LITERAL),
	CNTRL_ENTRY(VSTART,	CNTRL_BOTH),
	CNTRL_ENTRY(VSTOP,	CNTRL_BOTH),
#ifdef VSTATUS
	CNTRL_ENTRY(VSTATUS,	CNTRL_CANON),
#endif
	{ 0, NULL, 0 },
};

/*
 * I only care about local modes personally, but the other tables are present to
 * avoid putting up any barriers if more modes are useful to someone else.
 */
#define	MODE_ENTRY(c)		{ c, #c }
const struct orchlua_tty_mode orchlua_input_modes[] = {
	{ 0, NULL },
};

const struct orchlua_tty_mode orchlua_output_modes[] = {
	{ 0, NULL },
};

const struct orchlua_tty_mode orchlua_cntrl_modes[] = {
	{ 0, NULL },
};

const struct orchlua_tty_mode orchlua_local_modes[] = {
	MODE_ENTRY(ECHO),
	MODE_ENTRY(ECHOE),
	MODE_ENTRY(ECHOK),
	MODE_ENTRY(ECHONL),
	MODE_ENTRY(ICANON),
	MODE_ENTRY(IEXTEN),
	MODE_ENTRY(ISIG),
	MODE_ENTRY(NOFLSH),
	MODE_ENTRY(TOSTOP),
	{ 0, NULL },
};

static void
orchlua_term_fetch_cc(lua_State *L, struct termios *term)
{
	const struct orchlua_tty_cntrl *iter;
	cc_t cc;

	for (iter = &orchlua_cntrl_chars[0]; iter->cntrl_name != NULL; iter++) {
		cc = term->c_cc[iter->cntrl_idx];

		if ((iter->cntrl_flags & CNTRL_LITERAL) != 0)
			lua_pushinteger(L, cc);
		else if (cc == _POSIX_VDISABLE)
			lua_pushstring(L, "");
		else if (cc == 0177)
			lua_pushstring(L, "^?");
		else
			lua_pushfstring(L, "^%c", cc + 0x40);

		lua_setfield(L, -2, iter->cntrl_name);
	}
}

static int
orchlua_term_fetch(lua_State *L)
{
	struct orch_term *self;
	const char *which;
	int retvals = 0, top;

	self = luaL_checkudata(L, 1, ORCHLUA_TERMHANDLE);
	if ((top = lua_gettop(L)) < 2) {
		lua_pushnil(L);
		return (1);
	}

	for (int i = 1; i < top; i++) {
		which = luaL_checkstring(L, i + 1);

		if (strcmp(which, "iflag") == 0) {
			lua_pushnumber(L, self->term.c_iflag);
		} else if (strcmp(which, "oflag") == 0) {
			lua_pushnumber(L, self->term.c_oflag);
		} else if (strcmp(which, "cflag") == 0) {
			lua_pushnumber(L, self->term.c_cflag);
		} else if (strcmp(which, "lflag") == 0) {
			lua_pushnumber(L, self->term.c_lflag);
		} else if (strcmp(which, "cc") == 0) {
			lua_newtable(L);
			orchlua_term_fetch_cc(L, &self->term);
		} else {
			lua_pushnil(L);
		}

		retvals++;
	}

	return (retvals);
}

static int
orchlua_term_update_cc(lua_State *L, struct termios *term)
{
	const struct orchlua_tty_cntrl *iter;
	int type;
	cc_t cc;

	for (iter = &orchlua_cntrl_chars[0]; iter->cntrl_name != NULL; iter++) {
		type = lua_getfield(L, -1, iter->cntrl_name);
		if (type == LUA_TNIL) {
			lua_pop(L, 1);
			continue;
		}

		if ((iter->cntrl_flags & CNTRL_LITERAL) != 0) {
			int valid;

			cc = lua_tonumberx(L, -1, &valid);
			if (!valid) {
				luaL_pushfail(L);
				lua_pushfstring(L, "expected number for cc '%s'",
				    iter->cntrl_name);
				return (2);
			}
		} else {
			const char *str;
			size_t len;

			if (type != LUA_TSTRING) {
				luaL_pushfail(L);
				lua_pushfstring(L, "expected string for cc '%s'",
				    iter->cntrl_name);
				return (2);
			}

			str = lua_tolstring(L, -1, &len);
			if (len == 0) {
				cc = _POSIX_VDISABLE;
			} else if (len != 2 || str[0] != '^') {
				luaL_pushfail(L);
				lua_pushfstring(L,
				    "malformed value for cc '%s': %s",
				    iter->cntrl_name, str);
				return (2);
			} else if (str[1] != '?' &&
			    (str[1] < 0x40 || str[1] > 0x5f)) {
				luaL_pushfail(L);
				lua_pushfstring(L,
				    "cntrl char for cc '%s' out of bounds: %c",
				    iter->cntrl_name, str[1]);
				return (2);
			} else {
				if (str[1] == '?')
					cc = 0177;
				else
					cc = str[1] - 0x40;
			}
		}

		term->c_cc[iter->cntrl_idx] = cc;
		lua_pop(L, 1);
	}

	return (0);
}

static int
orchlua_term_update(lua_State *L)
{
	const char *fields[] = { "iflag", "oflag", "lflag", "cc", NULL };
	struct orch_term *self;
	struct orch_ipc_msg *msg;
	const char **fieldp, *field;
	struct termios *msgterm, updated;
	size_t msgsz;
	int error, mask, type, valid;

	self = luaL_checkudata(L, 1, ORCHLUA_TERMHANDLE);
	if (!lua_istable(L, 2)) {
		luaL_pushfail(L);
		lua_pushstring(L, "argument #2 must be table of fields to update");
		return (2);
	}

	lua_settop(L, 2);

	updated = self->term;
	for (fieldp = &fields[0]; *fieldp != NULL; fieldp++) {
		field = *fieldp;

		type = lua_getfield(L, -1, field);
		if (type == LUA_TNIL) {
			lua_pop(L, 1);
			continue;
		}

		if (strcmp(field, "iflag") == 0) {
			updated.c_iflag = lua_tonumberx(L, -1, &valid);
			if (!valid) {
				luaL_pushfail(L);
				lua_pushstring(L, "iflag must be a numeric mask");
				return (2);
			}
		} else if (strcmp(field, "oflag") == 0) {
			updated.c_oflag = lua_tonumberx(L, -1, &valid);
			if (!valid) {
				luaL_pushfail(L);
				lua_pushstring(L, "oflag must be a numeric mask");
				return (2);
			}
		} else if (strcmp(field, "cflag") == 0) {
			updated.c_cflag = lua_tonumberx(L, -1, &valid);
			if (!valid) {
				luaL_pushfail(L);
				lua_pushstring(L, "cflag must be a numeric mask");
				return (2);
			}
		} else if (strcmp(field, "lflag") == 0) {
			updated.c_lflag = lua_tonumberx(L, -1, &valid);
			if (!valid) {
				luaL_pushfail(L);
				lua_pushstring(L, "lflag must be a numeric mask");
				return (2);
			}
		} else if (strcmp(field, "cc") == 0) {
			if (type != LUA_TTABLE) {
				luaL_pushfail(L);
				lua_pushstring(L, "cc must be a table of characters to remap");
				return (2);
			}

			if ((error = orchlua_term_update_cc(L, &updated)) != 0)
				return (error);
		}

		lua_pop(L, 1);
	}

	self->term = updated;

	msg = orch_ipc_msg_alloc(IPC_TERMIOS_SET, sizeof(self->term),
	    (void **)&msgterm);
	if (msg == NULL) {
		luaL_pushfail(L);
		lua_pushstring(L, strerror(ENOMEM));
		return (2);
	}

	memcpy(msgterm, &self->term, sizeof(self->term));
	error = orch_ipc_send(self->proc->ipc, msg);
	if (error != 0)
		error = errno;

	orch_ipc_msg_free(msg);
	msg = NULL;

	if (error != 0) {
		luaL_pushfail(L);
		lua_pushstring(L, strerror(error));
		return (2);
	}

	/* Wait for ack */
	if (orch_ipc_wait(self->proc->ipc, NULL) == -1) {
		error = errno;
		goto err;
	}

	if (orch_ipc_recv(self->proc->ipc, &msg) != 0) {
		error = errno;
		goto err;
	} else if (msg == NULL) {
		luaL_pushfail(L);
		lua_pushstring(L, "unknown unexpected message received");
		return (2);
	} else if (orch_ipc_msg_tag(msg) != IPC_TERMIOS_ACK) {
		luaL_pushfail(L);
		lua_pushfstring(L, "unexpected message type '%d'",
		    orch_ipc_msg_tag(msg));
		orch_ipc_msg_free(msg);
		return (2);
	}

	orch_ipc_msg_free(msg);

	lua_pushboolean(L, 1);
	return (1);
err:
	luaL_pushfail(L);
	lua_pushstring(L, strerror(errno));
	return (2);
}

#define	ORCHTERM_SIMPLE(n) { #n, orchlua_term_ ## n }
static const luaL_Reg orchlua_term[] = {
	ORCHTERM_SIMPLE(fetch),
	ORCHTERM_SIMPLE(update),
	{ NULL, NULL },
};

static const luaL_Reg orchlua_term_meta[] = {
	{ "__index", NULL },	/* Set during registratino */
	/* Nothing to __gc / __close just yet. */
	{ NULL, NULL },
};

static void
register_term_metatable(lua_State *L)
{
	luaL_newmetatable(L, ORCHLUA_TERMHANDLE);
	luaL_setfuncs(L, orchlua_term_meta, 0);

	luaL_newlibtable(L, orchlua_term);
	luaL_setfuncs(L, orchlua_term, 0);
	lua_setfield(L, -2, "__index");

	lua_pop(L, 1);
}

static void
orchlua_tty_add_cntrl(lua_State *L, const char *name,
    const struct orchlua_tty_cntrl *mcntrl)
{
	const struct orchlua_tty_cntrl *iter;

	lua_newtable(L);
	for (iter = mcntrl; iter->cntrl_name != NULL; iter++) {
		lua_pushboolean(L, 1);
		lua_setfield(L, -2, iter->cntrl_name);
	}

	lua_setfield(L, -2, name);
}

static void
orchlua_tty_add_modes(lua_State *L, const char *name,
    const struct orchlua_tty_mode *mtable)
{
	const struct orchlua_tty_mode *iter;

	lua_newtable(L);
	for (iter = mtable; iter->mode_mask != 0; iter++) {
		lua_pushinteger(L, iter->mode_mask);
		lua_setfield(L, -2, iter->mode_name);
	}

	lua_setfield(L, -2, name);
}

int
orchlua_setup_tty(lua_State *L)
{

	/* Module is on the stack. */
	lua_newtable(L);

	/* tty.iflag, tty.oflag, tty.cflag, tty.lflag */
	orchlua_tty_add_modes(L, "iflag", &orchlua_input_modes[0]);
	orchlua_tty_add_modes(L, "oflag", &orchlua_output_modes[0]);
	orchlua_tty_add_modes(L, "cflag", &orchlua_cntrl_modes[0]);
	orchlua_tty_add_modes(L, "lflag", &orchlua_local_modes[0]);

	/* tty.cc */
	orchlua_tty_add_cntrl(L, "cc", &orchlua_cntrl_chars[0]);

	lua_setfield(L, -2, "tty");

	register_term_metatable(L);

	return (1);
}

int
orchlua_tty_alloc(lua_State *L, const struct orch_term *copy,
    struct orch_term **otermp)
{
	struct orch_term *term;

	term = lua_newuserdata(L, sizeof(*term));
	memcpy(term, copy, sizeof(*copy));

	*otermp = term;

	luaL_setmetatable(L, ORCHLUA_TERMHANDLE);
	return (1);
}
