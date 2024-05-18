all:	lib orch

lib: .PHONY
	${MAKE} -C lib/freebsd

ORCHSRC= contrib/orch

orch: .PHONY
	mkdir -p ${ORCHSRC}/build ${ORCHSRC}/install
	cmake -DCMAKE_INSTALL_PREFIX=${ORCHSRC}/install -S ${ORCHSRC} -B ${ORCHSRC}/build
	${MAKE} -C ${ORCHSRC}/build all install
