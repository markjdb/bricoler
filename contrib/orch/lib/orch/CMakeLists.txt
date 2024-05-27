file(GLOB share_orch_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/*.lua)
install(FILES ${share_orch_SOURCES}
	DESTINATION "${LUA_MODSHAREDIR}/orch")
