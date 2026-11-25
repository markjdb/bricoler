#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import json
from pathlib import Path
from typing import Dict

import cerberus

from bricoler.schemas import run_conf
from bricoler.util import sysctl


def load_run_config(path) -> Dict:
    """
    Load and validate a benchmark run configuration
    """
    path = Path(path)
    with path.open(mode="r") as file:
        config = json.load(file)

    v = cerberus.Validator(run_conf.schema)
    if not v.validate(config):
        raise ValueError(f"invalid run configuration: {v.errors}")
    return v.normalized(config)
