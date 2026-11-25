#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

#
# Schema describing a benchmark suite configuration file.  A suite contains a
# set of individual benchmarks, a build recipe, and a command used to run
# each benchmark.
#
schema = {
    "name": {
        "required": True,
        "type": "string",
    },
    "description": {
        "required": True,
        "type": "string",
    },
    "setup": {
        "required": False,
        "type": "dict",
        "schema": {
            "git": {
                "required": False,
                "type": "dict",
                "schema": {
                    "url": {"required": True, "type": "string"},
                    "branch": {"required": False, "type": "string"},
                },
            },
            # A list of packages required by the suite, installed with pkg(8).
            "requires": {
                "required": False,
                "type": "list",
                "schema": {"type": "string"},
            },
            # A list of commands run in the suite's directory after cloning.
            "recipe": {
                "required": False,
                "type": "list",
                "schema": {"type": "string"},
            },
        },
    },
    "run": {
        "required": True,
        "type": "dict",
        "schema": {
            # Command template used to run a single benchmark.
            "cmd": {"required": True, "type": "string"},
            # A list of environment variables, of the form "KEY=VALUE".
            "env": {
                "required": False,
                "type": "list",
                "default": [],
                "schema": {"type": "string"},
            },
        },
    },
    # The names of the benchmarks provided by this suite.
    "benchmarks": {
        "required": True,
        "type": "list",
        "schema": {"type": "string"},
    },
}
