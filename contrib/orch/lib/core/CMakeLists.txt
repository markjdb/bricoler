
file(GLOB core_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/*.c)

if("${CMAKE_SYSTEM_NAME}" STREQUAL "Linux")
	add_compile_options(-D_GNU_SOURCE)
endif()

add_library(core SHARED ${core_SOURCES})
set_target_properties(core PROPERTIES
	PREFIX "")
add_library(core_static STATIC ${core_SOURCES})

set(core_INCDIRS
	"${CMAKE_SOURCE_DIR}/include"
	"${CMAKE_SOURCE_DIR}/lib"
	"${LUA_INCLUDE_DIR}")

target_include_directories(core PRIVATE ${core_INCDIRS})
# orch(1) will link against the static lib
target_include_directories(core_static PRIVATE ${core_INCDIRS})

target_link_libraries(core "${LUA_LIBRARIES}")

# Disable all sanitizers for the dynamic library, because that requires us to
# also have a lua built with them enabled.  For our purposes, it's sufficient to
# just roll with a sanitizer-enabled static build since that's what we'll be
# using to run our tests.
target_compile_options(core PUBLIC -fno-sanitize=all)
target_link_options(core PUBLIC -fno-sanitize=all)

install(TARGETS core
	DESTINATION "${LUA_MODLIBDIR}/orch")
