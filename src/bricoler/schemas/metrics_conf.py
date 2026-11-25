#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

#
# Schema describing the metrics collected during a benchmark run.
#
schema = {
    "sysctl": {
        "type": "list",
        "schema": {
            "type": "dict",
            "schema": {
                "name": {"required": True, "type": "string"},
                "sampling_rate": {"required": False, "type": "integer"},
                "oids": {
                    "required": True,
                    "type": "list",
                    "schema": {"type": "string"},
                },
            },
        },
    },
    "ps": {
        "type": "list",
        "schema": {
            "type": "dict",
            "schema": {
                "command": {"required": True, "type": "string"},
                "stats": {
                    "required": True,
                    "type": "list",
                    "schema": {"type": "string"},
                },
                "sampling_rate": {"required": False, "type": "integer"},
            },
        },
    },
}
