#
# Copyright (c) Bojan Novković <bnovkov@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import logging as log

from threading import Thread, Event
from typing import Dict, List, Tuple, Type, Optional

import json
import cerberus
import subprocess

from bricoler.schemas import metrics_conf
from bricoler.util import sysctl

DEFAULT_SAMPLING_RATE_MS = 1000


def _parse_cpu_time(value: str) -> float:
    """
    Convert a ps(1) 'time' string to a number of seconds.
    """
    days = 0
    if "-" in value:
        days_str, _, value = value.partition("-")
        days = int(days_str)
    seconds = 0.0
    for field in value.split(":"):
        seconds = seconds * 60.0 + float(field)
    return days * 86400.0 + seconds


class Metric:
    """
    Base class for all metrics. We distinguish between twotypes of metrics:
     'diff' metrics - sample before and after each benchmark run,
     'continuous' - sampled periodically through a backgound thread
    """

    def __init__(self, config_dict: Dict):
        # Fall back to the default sampling rate if none was specified.
        self.sampling_rate = config_dict.get("sampling_rate", DEFAULT_SAMPLING_RATE_MS)

    def reset(self) -> None:
        pass

    def sample(self) -> None:
        pass

    def get_results(self, results_dict: Dict) -> None:
        pass


class SysctlMetric(Metric):
    """
    Sample one or more sysctls.
    """

    def __init__(self, config_dict: Dict) -> None:
        super().__init__(config_dict)
        self.oids = config_dict["oids"]
        self.name = config_dict["name"]
        self.values: Dict[str, List] = {oid: [] for oid in self.oids}

        log.debug(f"Registered sysctl metric group: '{self.name}'")

    def sample(self) -> None:
        for oid in self.oids:
            self.values[oid].append(sysctl(oid))
            log.debug(f"Sampled sysctl '{oid}'")

    def get_results(self, results_dict: Dict) -> None:
        results = results_dict.setdefault("sysctl", {})
        for oid in self.oids:
            results[oid] = self.values[oid].copy()

    def reset(self) -> None:
        for oid in self.oids:
            self.values[oid].clear()


class PsMetric(Metric):
    """
    Parse various statistics reported by ps(1) using the libxo json output.
    Currently only the process' cumulative CPU time ("time") can be sampled.
    """

    supported_stats = {
        "time",
    }

    def __init__(self, config_dict: Dict) -> None:
        super().__init__(config_dict)

        self.cmd = config_dict["command"]
        self.stats = config_dict["stats"]
        self.values: Dict[str, List] = {}

        for stat in self.stats:
            if stat not in PsMetric.supported_stats:
                raise ValueError(f"Sampling 'ps' metric '{stat}' is not supported yet")
            self.values[stat] = []

        log.debug(
            f"Registered 'ps' metric for process '{self.cmd}' - tracking '{self.stats}'"
        )

    def proc_info(self, pid: int) -> Optional[Dict]:
        ps_dict = None
        result = subprocess.run(
            ["ps", "x", "-p", str(pid), "--libxo", "json", "-o", "cputime"],
            stdout=subprocess.PIPE,
        )

        try:
            ps_dict = json.loads(result.stdout)
            return ps_dict
        except Exception as e:
            log.exception(e, exc_info=True)
        return None

    def sample(self) -> None:
        pid = MetricRegistry.target_pid
        if pid is None:
            raise ValueError("Tried to sample 'ps' metric without a target PID")
        proc_stat = self.proc_info()
        if pid not in proc_stat:
            # The benchmark process has already exited.
            log.debug(f"Benchmark process {pid} is no longer running")
            return
        for stat in self.stats:
            match stat:
                case "time":
                    self.values[stat].append(_tree_cpu_time(tree, pid))
        log.debug(f"Sampled ps metric '{self.name}' for process {pid}")

    def get_results(self, results_dict: Dict) -> None:
        results = results_dict.setdefault("ps", {})
        cmd_results = results.setdefault(self.cmd, {})
        for stat in self.stats:
            cmd_results[stat] = self.values[stat].copy()

    def reset(self) -> None:
        for stat in self.stats:
            self.values[stat].clear()


class MetricRegistry:
    diff_metrics: List[Metric] = []
    continuous_metrics: Dict[int, List[Metric]] = {}
    tq: List[Tuple[Thread, Event]] = []
    target_pid: Optional[int] = None

    @staticmethod
    def load_metrics(metrics: Dict) -> None:
        """
        Initialize the metrics requested by a run configuration.
        """
        MetricRegistry.diff_metrics.clear()
        MetricRegistry.continuous_metrics.clear()
        MetricRegistry.tq.clear()

        v = cerberus.Validator(metrics_conf.schema)
        if not v.validate(metrics):
            raise ValueError(f"invalid metrics configuration: {v.errors}")

        for metric_class, configs in metrics.items():
            ctor: Type[Metric]
            match metric_class:
                case "sysctl":
                    ctor = SysctlMetric
                case "ps":
                    ctor = PsMetric
                case _:
                    raise ValueError(f"'{metric_class}': Unknown metric class")
            for config in configs:
                m = ctor(config)
                if "sampling_rate" in config:
                    sampling_rate = config["sampling_rate"]
                    MetricRegistry.continuous_metrics.setdefault(
                        sampling_rate, []
                    ).append(m)
                else:
                    MetricRegistry.diff_metrics.append(m)

    @staticmethod
    def sample_diff_metrics():
        for m in MetricRegistry.diff_metrics:
            m.sample()

    @staticmethod
    def start_sampling_threads():
        def sampling_thread(
            metrics: List[Metric], sampling_ms: int, stop: Event
        ) -> None:
            while not stop.wait(sampling_ms / 1000.0):
                for m in metrics:
                    m.sample()

        if len(MetricRegistry.continuous_metrics) == 0:
            return

        MetricRegistry.tq.clear()
        for sampling_rate, metrics in MetricRegistry.continuous_metrics.items():
            stop = Event()
            t = Thread(
                target=sampling_thread,
                args=(metrics, sampling_rate, stop),
                daemon=True,
                name=f"metric-sampling-{sampling_rate}ms",
            )
            MetricRegistry.tq.append((t, stop))

        for t, _ in MetricRegistry.tq:
            t.start()

    @staticmethod
    def stop_sampling_threads():
        for _, stop in MetricRegistry.tq:
            stop.set()

        for t, _ in MetricRegistry.tq:
            t.join()
        MetricRegistry.tq.clear()

    @staticmethod
    def fetch_results() -> Dict:
        """
        Return the metrics collected during this run.
        """
        results: Dict = {"sysctl": {}, "ps": {}}
        for m in MetricRegistry.diff_metrics:
            m.get_results(results)
            m.reset()

        for metrics_list in MetricRegistry.continuous_metrics.values():
            for m in metrics_list:
                m.get_results(results)
                m.reset()

        return results
