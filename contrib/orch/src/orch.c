/*-
 * Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
 *
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "orch.h"
#include "orch_bin.h"

#ifndef __dead2
#define	__dead2	__attribute__((noreturn))
#endif

static void __dead2
usage(const char *name, int error)
{
	FILE *f;

	if (error == 0)
		f = stdout;
	else
		f = stderr;

	fprintf(f, "usage: %s [-f file] [command [argument ...]]\n", name);
	exit(error);
}

int
main(int argc, char *argv[])
{
	const char *invoke_path = argv[0];
	const char *scriptf = "-";	/* stdin */
	int ch;

	while ((ch = getopt(argc, argv, "f:h")) != -1) {
		switch (ch) {
		case 'f':
			scriptf = optarg;
			break;
		case 'h':
			usage(invoke_path, 0);
		default:
			usage(invoke_path, 1);
		}
	}

	argc -= optind;
	argv += optind;

	/*
	 * If we have a command supplied, we'll spawn() it for the script just to
	 * simplify things.  If we didn't, then the script just needs to make sure
	 * that it spawns something before a match/one block.
	 */
	return (orch_interp(scriptf, invoke_path, argc,
	    (const char * const *)argv));
}
