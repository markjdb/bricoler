SHLIB_NAME=	getaddrinfo.so

SRCS+=		lua_getaddrinfo.c

CFLAGS+=	-I/usr/local/include/lua54	\
		-I${.CURDIR}/../

WARNS?=		6

.include <bsd.lib.mk>
