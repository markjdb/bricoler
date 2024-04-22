SHLIB_NAME=	posix_spawn.so

SRCS+=		lua_posix_spawn.c

CFLAGS+=	-I/usr/local/include/lua54	\
		-I${.CURDIR}/../

WARNS?=		6

.include <bsd.lib.mk>
