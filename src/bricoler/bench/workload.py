#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import json
import logging as log
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from importlib import resources
from pathlib import Path
from typing import Dict, Optional, Tuple

import cerberus

from multiprocessing import Process, Semaphore

from bricoler.git import GitRepository
from bricoler.schemas import bench_conf
from bricoler.util import run_cmd, install_missing_packages

from .metric import MetricRegistry


def expand_template(template: str, benchname: str, ncpu: int) -> str:
    """
    Expand the benchmark template, filling in various keyword parameters.
    """
    return template.replace("{benchname}", benchname).replace("{ncpu}", str(ncpu))


def _parse_time_output(path) -> Dict[str, float]:
    """
    Parse the output of "time -p" into a dict of real/user/sys times.
    """
    stats: Dict[str, float] = {}
    try:
        with open(path, "r") as f:
            for line in f:
                kind, _, value = line.strip().partition(" ")
                if kind in ("real", "user", "sys"):
                    try:
                        stats[kind] = float(value)
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return stats


def find_suite_config(name: str):
    """
    Locate the configuration file of a benchmark suite.  Configurations found
    in ./benchmarks take precedence over those shipped with bricoler, so that
    suites can be customized locally.
    """
    local = Path("./benchmarks") / f"{name}.conf"
    if local.is_file():
        return local

    packaged = resources.files("bricoler") / "bench" / "benchmarks" / f"{name}.conf"
    if packaged.is_file():
        return packaged

    raise ValueError(
        f"Could not find a configuration for benchmark suite '{name}': "
        f"looked in {local} and in bricoler's packaged benchmark suites"
    )


def load_suite_config(name: str) -> Dict:
    """
    Parse and validate the JSON definition of a benchmark suite.
    """
    config_path = find_suite_config(name)
    with config_path.open("r") as file:
        try:
            config = json.load(file)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Benchmark suite configuration '{config_path}' is not "
                f"valid JSON: {e}"
            ) from e

    v = cerberus.Validator(bench_conf.schema)
    if not v.validate(config):
        raise ValueError(f"{name}: invalid benchmark suite configuration: {v.errors}")
    config = v.normalized(config)
    log.info("Loaded benchmark suite configuration for '%s'", name)
    return config


def load_workloads(run_config: Dict) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """
    Process the benchmark suite configurations selected by a workload
    configuration.
    """
    suites: Dict[str, Dict] = {}
    workloads: Dict[str, Dict] = {}

    for bench_pair in run_config["benchmarks"]:
        suite_name, sep, bench_name = bench_pair.partition(":")
        if not sep:
            raise ValueError(
                f"Invalid benchmark identifier '{bench_pair}': expected "
                "'<suite>:<benchmark>'"
            )

        if suite_name not in suites:
            suites[suite_name] = load_suite_config(suite_name)
        suite = suites[suite_name]

        if bench_name not in suite["benchmarks"]:
            raise ValueError(
                f"Benchmark '{bench_name}' missing from benchmark suite "
                f"'{suite_name}'"
            )
        if bench_pair not in workloads:
            log.info("Registered workload '%s'", bench_pair)

        workloads[bench_pair] = {
            "suite": suite_name,
            "benchmark": bench_name,
            "cmd": suite["run"]["cmd"],
            "env": suite["run"]["env"],
            "iterations": run_config["iterations"],
        }

    return suites, workloads


def setup_suites(
    suites: Dict[str, Dict],
    workloads: Dict[str, Dict],
) -> Tuple[Dict[str, Path], Dict[str, Optional[str]]]:
    """
    Build each benchmark suite selected by 'workloads'.
    Creates a marker file after each successful build
    to skip redundant rebuilds in the future.
    """
    if not workloads:
        raise ValueError("no workloads registered")

    suite_dirs: Dict[str, Path] = {}
    suite_revisions: Dict[str, Optional[str]] = {}
    for name, suite in suites.items():
        if not any(w["suite"] == name for w in workloads.values()):
            continue

        sdir = (Path.cwd() / "run" / name).resolve()
        sdir.mkdir(parents=True, exist_ok=True)
        suite_dirs[name] = sdir

        setup = suite.get("setup")
        repo = None
        if setup is not None and "git" in setup:
            git_conf = setup["git"]
            repo = GitRepository(
                git_conf["url"],
                sdir,
                branch=git_conf.get("branch"),
                shallow=True,
            )

        marker = sdir / ".bricoler-bench-built"
        if marker.exists():
            log.info(f"Benchmark suite '{name}' is already set up")
        else:
            log.info(f"Setting up benchmark suite '{name}'")
            if setup is not None:
                if "requires" in setup:
                    log.info("Checking required packages: %s", {*setup["requires"]})
                    install_missing_packages(setup["requires"])

                for cmd_str in setup.get("recipe", []):
                    run_cmd(shlex.split(cmd_str), check_result=True, cwd=sdir)
            marker.touch()

        suite_revisions[name] = (
            repo.checked_out_revision() if repo is not None else None
        )

    return suite_dirs, suite_revisions


def run_workloads(
    workloads: Dict[str, Dict],
    suite_dirs: Dict[str, Path],
    ncpu: int,
    verbose: bool = False,
) -> Dict:
    """
    Run each workload 'iterations' times.  Return a dict of
    per-workload, per-iteration results.
    """
    if not workloads:
        raise ValueError("no workloads registered; call load_workloads() first")

    logs_dir = Path("./logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # time(1) is used to record the real/user/sys CPU time of each
    # benchmark in addition to the wall-clock time measured here.
    time_cmd = shutil.which("time")
    if time_cmd is None:
        raise ValueError("time(1) was not found in PATH")

    results: Dict = {}
    for name, workload in workloads.items():
        suite_name = workload["suite"]
        if suite_name not in suite_dirs:
            raise ValueError(
                f"Benchmark suite '{suite_name}' has not been set up; "
                "run the setup action first"
            )
        suite_dir = suite_dirs[suite_name]

        # Convert the suite's environment overrides into a dict.
        env = None
        if workload["env"]:
            env = os.environ.copy()
            for entry in workload["env"]:
                key, _, value = entry.partition("=")
                env[key] = value

        argv = shlex.split(
            expand_template(
                workload["cmd"],
                benchname=workload["benchmark"],
                ncpu=ncpu,
            )
        )

        run_results: Dict = {}
        for i in range(workload["iterations"]):
            log.info(f"Running '{name}', iteration {i + 1} of {workload['iterations']}")
            sema = Semaphore(1)

            fd, timefile = tempfile.mkstemp()
            os.close(fd)
            logfile = logs_dir / f"{name.replace(':', '-')}-{i}.log"

            with logfile.open("wb") as out:
                try:
                    def paused_proc():
                        sema.acquire()
                        subprocess.run(
                            [time_cmd, "-p", "-o", timefile, "--", *argv],
                            cwd=suite_dir,
                            env=env,
                            stdout=out,
                            stderr=subprocess.STDOUT,
                        )
                    proc = Process(
                        target=paused_proc,
                    )
                    sema.release()
                    MetricRegistry.target_pid = proc.pid
                    MetricRegistry.start_sampling_threads()
                    # Sample diff metrics before resuming the benchmark process.
                    MetricRegistry.sample_diff_metrics()

                    sema.acquire()
                    proc.start()
                    start_ts = time.perf_counter()
                    sema.release()
                    proc.join()
                    end_ts = time.perf_counter()
                finally:
                    MetricRegistry.target_pid = None
                    MetricRegistry.stop_sampling_threads()
                    # Sample diff metrics now that the benchmark finished.
                    MetricRegistry.sample_diff_metrics()

            if proc is None or proc.exitcode != 0:
                raise ValueError(
                    f"Benchmark '{name}' failed with exit code "
                    f"{proc.exitcode}; see {logfile}"
                )
            if verbose:
                log.info("Benchmark output:\n%s", logfile.read_text(errors="replace"))

            run_results[i] = {
                "time": end_ts - start_ts,
                "cpu_time": _parse_time_output(timefile),
                "metrics": MetricRegistry.fetch_results(),
            }
            os.unlink(timefile)

        results[name] = run_results

    return results
