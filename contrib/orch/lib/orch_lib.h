/*-
 * Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#pragma once

#include <sys/types.h>

#include <stdbool.h>
#include <termios.h>

#include <lua.h>
#include <lauxlib.h>

/* We only support Lua 5.3+ */

/* Introduced in Lua 5.4 */
#ifndef luaL_pushfail
#define	luaL_pushfail(L)	lua_pushnil(L)
#endif

struct orch_ipc_msg;
typedef struct orch_ipc *orch_ipc_t;

struct orch_term;

enum orch_ipc_tag {
	IPC_NOXMIT = 0,
	IPC_RELEASE,		/* Bidrectional */
	IPC_ERROR,		/* Child -> Parent */
	IPC_TERMIOS_INQUIRY,	/* Parent -> Child */
	IPC_TERMIOS_SET,	/* Bidirectional */
	IPC_TERMIOS_ACK,	/* Child -> Parent */
	IPC_LAST,
};

struct orch_process {
	lua_State		*L;
	struct orch_term	*term;
	orch_ipc_t		 ipc;
	int			 cmdsock;
	pid_t			 pid;
	int			 status;
	int			 termctl;
	bool			 raw;
	bool			 released;
	bool			 eof;
	bool			 buffered;
	bool			 error;
};

struct orch_term {
	struct termios		term;
	struct orch_process	*proc;
	bool			initialized;
};

struct orchlua_tty_cntrl {
	int		 cntrl_idx;
	const char	*cntrl_name;
	int		 cntrl_flags;
};

struct orchlua_tty_mode {
	int		 mode_mask;
	const char	*mode_name;
};

#define	CNTRL_CANON	0x01
#define	CNTRL_NCANON	0x02
#define	CNTRL_BOTH	0x03
#define	CNTRL_LITERAL	0x04

/* orch_ipc.c */
typedef int (orch_ipc_handler)(orch_ipc_t, struct orch_ipc_msg *, void *);
int orch_ipc_close(orch_ipc_t);
orch_ipc_t orch_ipc_open(int);
bool orch_ipc_okay(orch_ipc_t);
int orch_ipc_recv(orch_ipc_t, struct orch_ipc_msg **);
struct orch_ipc_msg *orch_ipc_msg_alloc(enum orch_ipc_tag, size_t, void **);
void *orch_ipc_msg_payload(struct orch_ipc_msg *, size_t *);
enum orch_ipc_tag orch_ipc_msg_tag(struct orch_ipc_msg *);
void orch_ipc_msg_free(struct orch_ipc_msg *);
int orch_ipc_register(orch_ipc_t, enum orch_ipc_tag, orch_ipc_handler *, void *);
int orch_ipc_send(orch_ipc_t, struct orch_ipc_msg *);
int orch_ipc_send_nodata(orch_ipc_t, enum orch_ipc_tag);
int orch_ipc_wait(orch_ipc_t, bool *);

/* orch_spawn.c */
int orch_release(orch_ipc_t);
int orch_spawn(int, const char *[], struct orch_process *, orch_ipc_handler *);

/* orch_tty.c */
int orchlua_setup_tty(lua_State *);
int orchlua_tty_alloc(lua_State *, const struct orch_term *,
    struct orch_term **);

extern const struct orchlua_tty_cntrl orchlua_cntrl_chars[];
extern const struct orchlua_tty_mode orchlua_input_modes[];
extern const struct orchlua_tty_mode orchlua_output_modes[];
extern const struct orchlua_tty_mode orchlua_cntrl_modes[];
extern const struct orchlua_tty_mode orchlua_local_modes[];
