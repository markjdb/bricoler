add_custom_target(check
	COMMAND env ORCHBIN="${CMAKE_BINARY_DIR}/src/orch" ORCHLUA_PATH="${CMAKE_SOURCE_DIR}/lib" sh "${CMAKE_CURRENT_SOURCE_DIR}/basic_test.sh")
