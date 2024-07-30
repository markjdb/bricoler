all:	lib orch

lib: .PHONY
	${MAKE} -C lib/freebsd

install:
	@echo "No install target is supported, run in-place"
	@false

ORCHSRC= ${.CURDIR}/contrib/orch

.if ${MACHINE} == "arm64" && ${MACHINE_ARCH} == "aarch64c"
ORCHLIBS=-DLUA_LIBRARIES=/usr/local/lib/liblua-5.4.so
ORCHINCS=-DLUA_INCLUDE_DIR=/usr/local/include/lua54
.endif

orch: .PHONY
	mkdir -p ${ORCHSRC}/build ${ORCHSRC}/install
	cmake -DCMAKE_INSTALL_PREFIX=${ORCHSRC}/install \
	    ${ORCHLIBS} ${ORCHINCS} \
	    -S ${ORCHSRC} -B ${ORCHSRC}/build
	${MAKE} -C ${ORCHSRC}/build all install
