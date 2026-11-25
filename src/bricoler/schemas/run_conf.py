#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

#
# Schema describing a benchmark run configuration.
#
from . import metrics_conf

schema = {
    "benchmarks": {
        "required": True,
        "type": "list",
        "schema": {"type": "string"},
    },
    "description": {
        "required": False,
        "type": "string",
    },
    "iterations": {
        "required": True,
        "type": "integer",
        "min": 1,
    },
    "metrics": {
        "required": True,
        "type": "dict",
        "schema": metrics_conf.schema,
    },
}
