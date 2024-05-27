cmake_minimum_required(VERSION 3.18)

project(orch)

find_package("Lua")

if(NOT LUA_FOUND)
	message(FATAL_ERROR "No Lua installation found; please install Lua")
endif()

set(LUA_MODLIBDIR "lib/lua/${LUA_VERSION_MAJOR}.${LUA_VERSION_MINOR}"
	CACHE PATH "Path to install lua dynamic library modules into")
set(LUA_MODSHAREDIR "share/lua/${LUA_VERSION_MAJOR}.${LUA_VERSION_MINOR}"
	CACHE PATH "Path to install lua modules into")
if(IS_ABSOLUTE "${LUA_MODSHAREDIR}")
	set(ORCHLUA_PATH "${LUA_MODSHAREDIR}"
		CACHE PATH "Path to install orch.lua into")
else()
	set(ORCHLUA_PATH "${CMAKE_INSTALL_PREFIX}/${LUA_MODSHAREDIR}"
		CACHE PATH "Path to install orch.lua into")
endif()
set(ORCHLUA_BINDIR "bin"
	CACHE PATH "Path to install orch(1) into")
set(ORCHLUA_EXAMPLESDIR "share/examples/${CMAKE_PROJECT_NAME}"
	CACHE PATH "Path to install .orch examples into")

option(EXAMPLES "Install examples" ON)
option(MANPAGES "Install manpages" ON)
option(BUILD_DRIVER "Build the orch(1) driver" ON)

set(warnings "-Wall -Wextra -Werror")
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
	add_compile_options(-fsanitize=address,undefined -fstrict-aliasing)
	add_link_options(-fsanitize=address,undefined -fstrict-aliasing)
endif()

if(EXAMPLES)
	add_subdirectory(examples)
endif()
add_subdirectory(lib)
if(MANPAGES)
	add_subdirectory(man)
endif()
if(BUILD_DRIVER)
	add_subdirectory(src)
endif()
add_subdirectory(tests)
