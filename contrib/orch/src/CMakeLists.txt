
file(GLOB orch_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/*.c)

add_compile_definitions(ORCHLUA_PATH="${ORCHLUA_PATH}")

add_executable(orch ${orch_SOURCES})

set(orch_INCDIRS "${CMAKE_SOURCE_DIR}/include" "${LUA_INCLUDE_DIR}")
target_include_directories(orch PRIVATE ${orch_INCDIRS})
target_link_libraries(orch core_static "${LUA_LIBRARIES}")

install(TARGETS orch
	DESTINATION "${ORCHLUA_BINDIR}")
