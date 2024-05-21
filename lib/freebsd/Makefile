SHLIB_NAME=	freebsd_meta.so

SRCS+=		lua_freebsd_meta.c

CFLAGS+=	-I/usr/local/include/lua54	\
		-I${.CURDIR}

WARNS?=		6

SUBDIR=	errno		\
	getaddrinfo	\
	libgen		\
	mktemp		\
	posix_spawn	\
	sys		\
	sysconf		\
	uname

.include <bsd.lib.mk>
.include <bsd.subdir.mk>
