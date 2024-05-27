
set(MANSECTIONS 1 5)

set(MAN1	orch.1)
set(MAN5	orch.5)

foreach(sect IN LISTS MANSECTIONS)
	foreach(page IN LISTS MAN${sect})
		install(FILES ${page} DESTINATION "share/man/man${sect}")
	endforeach()
endforeach()
