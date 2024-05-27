/*-
 * Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <sys/param.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>

#include <assert.h>
#include <err.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <regex.h>
#include <unistd.h>

#include "orch.h"
#include "orch_lib.h"

#ifdef __linux__
#define	CLOCK_REALTIME_FAST	CLOCK_REALTIME_COARSE
#endif

/* Fallback */
#ifndef CLOCK_REALTIME_FAST
#define	CLOCK_REALTIME_FAST	CLOCK_REALTIME
#endif

/* Not a huge deal if it's missing... */
#ifndef O_PATH
#define	O_PATH	0
#endif

#define	ORCHLUA_PROCESSHANDLE	"orchlua_process"
#define	ORCHLUA_REGEXHANDLE	"orchlua_regex_t"

static struct orchlua_cfg {
	int			 dirfd;
	bool			 initialized;
} orchlua_cfg = {
	.dirfd = -1,
	.initialized = false,
};

static int orchlua_add_execpath(const char *);

/*
 * Not exported
 */
static int
orchlua_close(lua_State *L)
{
	luaL_Stream *p;
	int ret;

	p = (luaL_Stream *)luaL_checkudata(L, 1, LUA_FILEHANDLE);
	ret = fclose(p->f);
	return (luaL_fileresult(L, ret == 0, NULL));
}

static int
orchlua_open_init(const char *filename, const char **script, bool alter_path)
{

	assert(!orchlua_cfg.initialized);
	assert(orchlua_cfg.dirfd == -1);

	/* stdin */
	if (strcmp(filename, "-") == 0) {
		*script = filename;
	} else {
		char spath[PATH_MAX];
		char *fpath, *walker;
		const char *scriptroot;

		if ((fpath = realpath(filename, &spath[0])) == NULL)
			err(1, "realpath: %s", filename);

		walker = strrchr(fpath, '/');
		if (walker != NULL) {
			*walker = '\0';
			scriptroot = fpath;
			*script = strdup(walker + 1);
		} else {
			scriptroot = ".";
			*script = strdup(fpath);
		}

		if (*script == NULL)
			return (ENOMEM);

		if (alter_path)
			orchlua_add_execpath(scriptroot);

		orchlua_cfg.dirfd = open(scriptroot,
		    O_DIRECTORY | O_PATH | O_CLOEXEC);
		if (orchlua_cfg.dirfd == -1)
			err(1, "open: %s", fpath);
	}

	orchlua_cfg.initialized = true;
	return (0);
}

static int
orchlua_reset(lua_State *L)
{

	if (orchlua_cfg.initialized) {
		if (orchlua_cfg.dirfd >= 0) {
			close(orchlua_cfg.dirfd);
			orchlua_cfg.dirfd = -1;
		}

		orchlua_cfg.initialized = false;
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
orchlua_open(lua_State *L)
{
	luaL_Stream *p;
	const char *filename, *script;
	int fd, rvals;
	bool alter_path;

	rvals = 1;
	filename = luaL_checkstring(L, 1);
	alter_path = lua_toboolean(L, 2);
	script = NULL;

	/* First open() sets up the sandbox state. */
	if (!orchlua_cfg.initialized) {
		int error;

		error = orchlua_open_init(filename, &script, alter_path);
		if (error != 0) {
			luaL_pushfail(L);
			lua_pushstring(L, strerror(error));
			return (true);
		}
	} else if (orchlua_cfg.dirfd == -1) {
		luaL_pushfail(L);
		lua_pushstring(L,
		    "No sandbox granted (script opened from stdin)");
		return (2);
	} else {
		script = filename;
	}

	fd = -1;
	if (orchlua_cfg.dirfd == -1) {
		assert(script == filename);
		fd = dup(STDIN_FILENO);
		if (fd == -1)
			return (luaL_fileresult(L, 0, "stdin"));
	}

	p = (luaL_Stream *)lua_newuserdata(L, sizeof(*p));
	p->closef = &orchlua_close;
	p->f = NULL;
	luaL_setmetatable(L, LUA_FILEHANDLE);

	if (fd == -1)
		fd = openat(orchlua_cfg.dirfd, script, O_RDONLY | O_CLOEXEC);
	if (fd != -1)
		p->f = fdopen(fd, "r");

	/*
	 * Check for errors up front, to avoid clobbering errno.  We don't want
	 * to use luaL_fileresult() for success because this particular API
	 * returns a file handle.
	 */
	if (p->f == NULL)
		rvals = luaL_fileresult(L, 0, filename);
	else
		rvals = 1;
	if (script != filename)
		free((void *)(uintptr_t)script);
	return (rvals);
}

static int
orchlua_regcomp(lua_State *L)
{
	const char *pattern;
	regex_t *regex;
	int error;

	pattern = luaL_checkstring(L, 1);

	regex = lua_newuserdata(L, sizeof(*regex));
	luaL_setmetatable(L, ORCHLUA_REGEXHANDLE);

	if ((error = regcomp(regex, pattern, REG_EXTENDED)) != 0) {
		char errbuf[64];

		(void)regerror(error, regex, errbuf, sizeof(errbuf));

		/* Pop the regex_t */
		lua_pop(L, 1);

		luaL_pushfail(L);
		lua_pushstring(L, errbuf);
		return (2);
	}

	return (1);
}

static int
orchlua_sleep(lua_State *L)
{
	lua_Number duration;
	struct timespec rtp;
	int ret;

	duration = luaL_checknumber(L, 1);
	rtp.tv_sec = floor(duration);
	rtp.tv_nsec = 1000000000 * (duration - rtp.tv_sec);

	/*
	 * We aren't guaranteeing anything about actual time delayed, just that
	 * we'll sleep at least the amount specified.  Let the timer run out.
	 */
	while ((ret = nanosleep(&rtp, &rtp)) == -1 && errno == EINTR) {
		continue;
	}

	if (ret == -1) {
		int serr = errno;

		luaL_pushfail(L);
		lua_pushstring(L, strerror(serr));
		return (2);
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
orchlua_time(lua_State *L)
{
	struct timespec tv;

	assert (clock_gettime(CLOCK_REALTIME_FAST, &tv) == 0);

	lua_pushnumber(L, tv.tv_sec);
	return (1);
}

static int
orchlua_child_error(orch_ipc_t ipc __unused, struct orch_ipc_msg *msg,
    void *cookie)
{
	struct orch_process *proc = cookie;
	const char *childstr;
	size_t datasz;

	childstr = orch_ipc_msg_payload(msg, &datasz);
	if (datasz != 0)
		fprintf(stderr, "CHILD ERROR: %.*s\n", (int)datasz, childstr);
	proc->error = true;
	return (0);
}

static int
orchlua_spawn(lua_State *L)
{
	struct orch_process *proc;
	const char **argv;
	int argc;

	if (lua_gettop(L) == 0) {
		luaL_pushfail(L);
		lua_pushstring(L, "No command specified to spawn");
		return (2);
	}

	/*
	 * The script can table.unpack its args, so we'll expect all strings even if
	 * they choose to build it up via table.
	 */
	argc = lua_gettop(L);
	argv = calloc(argc + 1, sizeof(*argv));

	for (int i = 0; i < argc; i++) {
		argv[i] = lua_tostring(L, i + 1);
		if (argv[i] == NULL) {
			free(argv);
			luaL_pushfail(L);
			lua_pushfstring(L, "Argument at index %d not a string", i + 1);
			return (2);
		}

	}

	/*
	 * Note that the one uservalue allowed by Lua < 5.4 is already consumed
	 * by the process buffer, so we can't allocate the orch_term for it up
	 * front.  We'll just allocate it if the module requests it, and will
	 * not attach it to the proc -- orch.lua will just have to manage its
	 * lifetime appropriately.
	 */
	proc = lua_newuserdata(L, sizeof(*proc));
	proc->L = L;
	proc->term = NULL;
	proc->status = 0;
	proc->pid = 0;
	proc->buffered = proc->eof = proc->released = false;
	proc->error = false;

	luaL_setmetatable(L, ORCHLUA_PROCESSHANDLE);

	if (orch_spawn(argc, argv, proc, &orchlua_child_error) != 0) {
		int serrno = errno;

		free(argv);

		luaL_pushfail(L);
		lua_pushstring(L, strerror(serrno));
		return (2);
	}

	free(argv);

	return (1);
}

#define	REG_SIMPLE(n)	{ #n, orchlua_ ## n }
static const struct luaL_Reg orchlib[] = {
	REG_SIMPLE(open),
	REG_SIMPLE(regcomp),
	REG_SIMPLE(reset),
	REG_SIMPLE(sleep),
	REG_SIMPLE(time),
	REG_SIMPLE(spawn),
	{ NULL, NULL },
};

static void
orchlua_process_close_alarm(int signo __unused)
{
	/* XXX Ignored, just don't terminate us. */
}

static bool
orchlua_process_killed(struct orch_process *self, int *signo)
{

	assert(self->pid != 0);
	if (waitpid(self->pid, &self->status, WNOHANG) != self->pid)
		return (false);

	if (WIFSIGNALED(self->status))
		*signo = WTERMSIG(self->status);
	else
		*signo = 0;
	self->pid = 0;

	return (true);
}

static int
orchlua_process_close(lua_State *L)
{
	struct orch_process *self;
	pid_t wret;
	int sig;
	bool failed;

	failed = false;
	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	if (self->pid != 0 && orchlua_process_killed(self, &sig) && sig != 0) {
		luaL_pushfail(L);
		lua_pushfstring(L, "spawned process killed with signal '%d'", sig);
		return (2);
	}

	if (self->pid != 0) {
		struct sigaction sigalrm = {
			.sa_handler = orchlua_process_close_alarm,
		};

		sigaction(SIGALRM, &sigalrm, NULL);

		/* XXX Configurable? */
		alarm(5);
		sig = SIGINT;
again:
		kill(self->pid, sig);
		wret = waitpid(self->pid, &self->status, 0);
		alarm(0);
		if (wret != self->pid) {
			failed = true;

			/* If asking nicely didn't work, just kill it. */
			if (sig != SIGKILL) {
				sig = SIGKILL;
				goto again;
			}
		}

		signal(SIGALRM, SIG_DFL);
		self->pid = 0;
	}

	orch_ipc_close(self->ipc);
	self->ipc = NULL;

	if (self->termctl != -1)
		close(self->termctl);
	self->termctl = -1;

	if (failed) {
		luaL_pushfail(L);
		lua_pushstring(L, "could not kill process with SIGINT");
		return (2);
	}

	lua_pushboolean(L, 1);
	return (1);
}

/*
 * read(callback[, timeout]) -- returns true if we finished, false if we
 * hit EOF, or a fail, error pair otherwise.
 */
static int
orchlua_process_read(lua_State *L)
{
	char buf[LINE_MAX];
	fd_set rfd;
	struct orch_process *self;
	struct timeval tv, *tvp;
	time_t start, now;
	ssize_t readsz;
	int fd, ret;
	lua_Number timeout;

	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	luaL_checktype(L, 2, LUA_TFUNCTION);

	if (lua_gettop(L) > 2) {
		timeout = luaL_checknumber(L, 3);
		if (timeout < 0) {
			luaL_pushfail(L);
			lua_pushstring(L, "Invalid timeout");
			return (2);
		} else {
			timeout = MAX(timeout, 1);
		}

		tv.tv_sec = timeout;
		tv.tv_usec = 0;
		tvp = &tv;
	} else {
		/* No timeout == block */
		tvp = NULL;
	}

	fd = self->termctl;
	FD_ZERO(&rfd);

	/* Crude */
	if (tvp != NULL)
			start = now = time(NULL);
	while ((tvp == NULL || now - start < timeout) && !self->error) {
		FD_SET(fd, &rfd);
		ret = select(fd + 1, &rfd, NULL, NULL, tvp);
		if (ret == -1 && errno == EINTR) {
			/*
			 * Rearm the timeout and go again; we'll just let the loop
			 * terminate with a negative tv.tv_sec if timeout seconds
			 * have elapsed.
			 */
			if (tvp != NULL) {
				now = time(NULL);
				tv.tv_sec = timeout - (now - start);
			}

			continue;
		} else if (ret == -1) {
			int err = errno;

			luaL_pushfail(L);
			lua_pushstring(L, strerror(err));
			return (2);
		} else if (ret == 0) {
			/* Timeout -- not the end of the world. */
			lua_pushboolean(L, 1);
			return (1);
		}

		/* Read it */
		readsz = read(fd, buf, sizeof(buf));

		/*
		 * Some platforms will return `0` when the slave side of a pty
		 * has gone away, while others will return -1 + EIO.  Convert
		 * the latter to the former.
		 */
		if (readsz == -1 && errno == EIO)
			readsz = 0;
		if (readsz < 0) {
			int err = errno;

			luaL_pushfail(L);
			lua_pushstring(L, strerror(err));
			return (2);
		} else {
			int nargs = 0;

			/*
			 * Duplicate the function value, it'll get popped by the call.
			 */
			lua_settop(L, 3);
			lua_copy(L, -2, -1);

			/* callback([data]) -- nil data == EOF */
			if (readsz > 0) {
				lua_pushlstring(L, buf, readsz);
				nargs++;
			}

			/*
			 * Callback should return true if it's done, false if it
			 * wants more.
			 */
			lua_call(L, nargs, 1);

			if (readsz == 0) {
				int signo;

				self->eof = true;

				assert(self->termctl >= 0);
				close(self->termctl);
				self->termctl = -1;

				if (orchlua_process_killed(self, &signo) && signo != 0) {
					luaL_pushfail(L);
					lua_pushfstring(L,
						"spawned process killed with signal '%d'", signo);
					return (2);
				}

				/*
				 * We need to be able to distinguish between a disaster
				 * scenario and possibly business as usual, so we'll
				 * return true if we hit EOF.  This lets us assert()
				 * on the return value and catch bad program exits.
				 */
				lua_pushboolean(L, 1);
				return (1);
			}

			if (lua_toboolean(L, -1))
				break;
		}
	}

	lua_pushboolean(L, 1);
	return (1);
}

static int
orchlua_process_write(lua_State *L)
{
	struct orch_process *self;
	const char *buf;
	size_t bufsz, totalsz;
	ssize_t writesz;
	int fd;

	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	buf = luaL_checklstring(L, 2, &bufsz);

	fd = self->termctl;
	totalsz = 0;
	while (totalsz < bufsz) {
		writesz = write(fd, &buf[totalsz], bufsz - totalsz);
		if (writesz == -1 && errno == EINTR) {
			continue;
		} else if (writesz == -1) {
			int err = errno;

			luaL_pushfail(L);
			lua_pushstring(L, strerror(err));
			return (2);
		}

		totalsz += writesz;
	}

	lua_pushnumber(L, totalsz);
	return (1);
}

static int
orchlua_process_release(lua_State *L)
{
	struct orch_process *self;
	int error;

	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);

	error = orch_release(self->ipc);
	orch_ipc_close(self->ipc);
	self->ipc = NULL;

	if (error != 0) {
		error = errno;

		luaL_pushfail(L);
		lua_pushstring(L, strerror(error));
		return (2);
	}

	self->released = true;

	lua_pushboolean(L, 1);
	return (1);
}

static int
orchlua_process_released(lua_State *L)
{
	struct orch_process *self;

	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	lua_pushboolean(L, self->released);
	return (1);
}

static int
orchlua_process_term_set(orch_ipc_t ipc __unused, struct orch_ipc_msg *msg,
    void *cookie)
{
	struct orch_term *term = cookie;
	struct termios *child_termios;
	struct termios *parent_termios = &term->term;
	size_t datasz;

	child_termios = orch_ipc_msg_payload(msg, &datasz);
	if (child_termios == NULL || datasz != sizeof(*child_termios)) {
		errno = EINVAL;
		return (-1);
	}

	memcpy(parent_termios, child_termios, sizeof(*child_termios));
	term->initialized = true;

	return (0);
}

static int
orchlua_process_term(lua_State *L)
{
	struct orch_term sterm;
	struct orch_ipc_msg *cmsg;
	struct orch_process *self;
	int error, retvals;

	retvals = 0;
	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	if (!orch_ipc_okay(self->ipc)) {
		luaL_pushfail(L);
		lua_pushstring(L, "process already released");
		return (2);
	} else if (self->term != NULL) {
		luaL_pushfail(L);
		lua_pushstring(L, "process term already generated");
		return (2);
	}

	sterm.proc = self;
	sterm.initialized = false;
	orch_ipc_register(self->ipc, IPC_TERMIOS_SET, orchlua_process_term_set,
	    &sterm);

	/*
	 * The client is only responding to our messages up until we release, so
	 * there shouldn't be anything in the queue.  We'll just fire this off,
	 * and wait for a response to become ready.
	 */
	if ((error = orch_ipc_send_nodata(self->ipc,
	    IPC_TERMIOS_INQUIRY)) != 0) {
		error = errno;
		goto out;
	}

	if (orch_ipc_wait(self->ipc, NULL) == -1) {
		error = errno;
		goto out;
	}

	if (orch_ipc_recv(self->ipc, &cmsg) != 0) {
		error = errno;
		goto out;
	}

	if (cmsg != NULL) {
		luaL_pushfail(L);
		lua_pushfstring(L, "unexpected message type '%d'",
		    orch_ipc_msg_tag(cmsg));

		orch_ipc_msg_free(cmsg);
		cmsg = NULL;

		retvals = 2;
		goto out;
	} else if (!sterm.initialized) {
		luaL_pushfail(L);
		lua_pushstring(L, "unknown unexpected message received");
		retvals = 2;
		goto out;
	}

	retvals = orchlua_tty_alloc(L, &sterm, &self->term);

out:
	/* Deallocate the slot */
	orch_ipc_register(self->ipc, IPC_TERMIOS_SET, NULL, NULL);
	if (error != 0 && retvals == 0) {
		luaL_pushfail(L);
		lua_pushstring(L, strerror(error));

		retvals = 2;
	}

	return (retvals);
}

static int
orchlua_process_eof(lua_State *L)
{
	struct orch_process *self;

	self = luaL_checkudata(L, 1, ORCHLUA_PROCESSHANDLE);
	lua_pushboolean(L, self->eof);
	return (1);
}

#define	PROCESS_SIMPLE(n)	{ #n, orchlua_process_ ## n }
static const luaL_Reg orchlua_process[] = {
	PROCESS_SIMPLE(close),
	PROCESS_SIMPLE(read),
	PROCESS_SIMPLE(write),
	PROCESS_SIMPLE(release),
	PROCESS_SIMPLE(released),
	PROCESS_SIMPLE(term),
	PROCESS_SIMPLE(eof),
	{ NULL, NULL },
};

static const luaL_Reg orchlua_process_meta[] = {
	{ "__index", NULL },	/* Set during registration */
	{ "__gc", orchlua_process_close },
	{ "__close", orchlua_process_close },
	{ NULL, NULL },
};

static void
register_process_metatable(lua_State *L)
{
	luaL_newmetatable(L, ORCHLUA_PROCESSHANDLE);
	luaL_setfuncs(L, orchlua_process_meta, 0);

	luaL_newlibtable(L, orchlua_process);
	luaL_setfuncs(L, orchlua_process, 0);
	lua_setfield(L, -2, "__index");

	lua_pop(L, 1);
}

static int
orchlua_regex_error(lua_State *L, regex_t *self, int error)
{
	char errbuf[64];

	(void)regerror(error, self, errbuf, sizeof(errbuf));

	luaL_pushfail(L);
	lua_pushstring(L, errbuf);
	return (2);
}

static int
orchlua_regex_find(lua_State *L)
{
	const char *subject;
	regex_t *self;
	regmatch_t match;
	int error;

	self = luaL_checkudata(L, 1, ORCHLUA_REGEXHANDLE);
	subject = luaL_checkstring(L, 2);

	error = regexec(self, subject, 1, &match, 0);
	if (error != 0) {
		if (error == REG_NOMATCH) {
			lua_pushnil(L);
			return (1);
		}

		return (orchlua_regex_error(L, self, error));
	}

	/*
	 * Lua's strings are one-indexed, so we bump rm_so by 1.  rm_eo is
	 * actually the the character just *after* the match, so we'll just take
	 * that as-is rather than - 1 + 1.
	 */
	lua_pushnumber(L, match.rm_so + 1);
	lua_pushnumber(L, match.rm_eo);
	return (2);
}

static int
orchlua_regex_close(lua_State *L)
{
	regex_t *self;

	self = luaL_checkudata(L, 1, ORCHLUA_REGEXHANDLE);
	regfree(self);
	return (0);
}

#define	REGEX_SIMPLE(n)	{ #n, orchlua_regex_ ## n }
static const luaL_Reg orchlua_regex[] = {
	REGEX_SIMPLE(find),
	{ NULL, NULL },
};

static const luaL_Reg orchlua_regex_meta[] = {
	{ "__index", NULL },	/* Set during registration */
	{ "__gc", orchlua_regex_close },
	{ "__close", orchlua_regex_close },
	{ NULL, NULL },
};

static void
register_regex_metatable(lua_State *L)
{
	luaL_newmetatable(L, ORCHLUA_REGEXHANDLE);
	luaL_setfuncs(L, orchlua_regex_meta, 0);

	luaL_newlibtable(L, orchlua_regex);
	luaL_setfuncs(L, orchlua_regex, 0);
	lua_setfield(L, -2, "__index");

	lua_pop(L, 1);
}

static int
orchlua_add_execpath(const char *path)
{
	const char *curpath;
	char *newpath;
	int error;

	error = 0;
	curpath = getenv("PATH");
	/* Odd, but nothing to do but just add it... */
	if (curpath == NULL)
		return (setenv("PATH", path, 1) == 0 ? 0 : errno);

	newpath = NULL;
	if (asprintf(&newpath, "%s:%s", path, curpath) == -1)
		return (ENOMEM);

	if (setenv("PATH", newpath, 1) != 0)
		error = errno;

	free(newpath);
	return (error);
}

/*
 * Available: functions above, orch_impl.script, orch_impl.script_root
 */
int
luaopen_orch_core(lua_State *L)
{

	luaL_newlib(L, orchlib);

	orchlua_setup_tty(L);

	register_process_metatable(L);
	register_regex_metatable(L);

	return (1);
}
