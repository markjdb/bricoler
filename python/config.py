#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import argparse
import fcntl
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


class Config:
    command_line_parameters: List[str] = []
    config_file_object: Dict[str, Any] = {}
    CONFIG_FILE_VERSION = 1
    config_path: Path
    files_dir: Path
    max_jobs: int = len(os.sched_getaffinity(0))
    parser: argparse.ArgumentParser
    skip: bool = False
    task_params: Dict[str, Dict[str, Any]] = {}
    workdir: Path
    uuid: uuid.UUID

    def __init__(self):
        self.files_dir = Path(sys.argv[0]).parent.resolve() / 'files'
        self.workdir = Path(os.environ.get('BRICOLER_WORKDIR',
                                           Path.home() / 'bricoler')).resolve()

        parser = argparse.ArgumentParser(prog='bricoler')
        parser.add_argument(
            '-a', '--alias',
            action='store',
            help='define an alias for the current command-line invocation')
        parser.add_argument(
            "-j", "--max-jobs",
            type=int,
            metavar='N',
            default=self.max_jobs,
            help='set the maximum number of concurrent jobs (default: number of CPUs)')
        parser.add_argument(
            '-l', '--list',
            action='store_true',
            help=argparse.SUPPRESS)  # only really meant for completion handlers
        parser.add_argument(
            '-s', '--show',
            action='store_true',
            help='show all available tasks or task parameters')
        parser.add_argument(
            '-S', '--skip',
            action='store_true',
            help='skip execution of dependent tasks')
        parser.add_argument(
            '-w', '--workdir',
            metavar='DIR',
            default=self.workdir,
            help='set the work directory (default: $BRICOLER_WORKDIR or ${HOME}/bricoler)')
        parser.add_argument(
            'task',
            nargs='?',
            help='the task to run')
        self.parser = parser

    @property
    def aliases(self) -> List[Dict[str, Any]]:
        return self.config_file_object['aliases']

    def add_alias(self, name: str):
        # Remove an existing alias.  Perhaps we should rename it instead?
        self.config_file_object['aliases'] = [
            a for a in self.config_file_object['aliases'] if a['alias'] != name
        ]
        self.config_file_object['aliases'].append({
            "alias": name,
            "task": self.task.name,
            "parameters": self.command_line_parameters,
        })
        with self.config_path.open('w') as f:
            json.dump(self.config_file_object, fp=f, indent=4)

    def lookup_alias(self, name: str) -> Optional[Dict[str, Any]]:
        return next(
            (a for a in self.config_file_object['aliases'] if a['alias'] == name),
            None
        )

    def load(self, lookup) -> argparse.Namespace:
        # Parse global arguments and the task name.
        opts, args = self.parser.parse_known_args()

        self.skip = opts.skip
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.config_path = Path(self.workdir / 'bricoler.json')

        # Load aliases from the configuration file.
        try:
            f = self.config_path.open('r')
        except FileNotFoundError:
            # Populate it with some initial structure.
            with self.config_path.open('w') as f:
                json.dump({
                    "aliases": [],
                    "uuid": str(uuid.uuid4()),
                    "version": Config.CONFIG_FILE_VERSION,
                }, fp=f, indent=4)
        finally:
            with self.config_path.open('r') as f:
                try:
                    self.config_file_object = json.load(f)
                except json.JSONDecodeError as e:
                    raise ValueError(
                        f"Configuration file '{self.config_path}' is not valid JSON: {e}"
                    ) from e

                version = self.config_file_object.get('version', -1)
                if version != Config.CONFIG_FILE_VERSION:
                    raise ValueError(
                        f"Unknown or unsupported configuration file version: {version}"
                    )
                try:
                    self.uuid = uuid.UUID(self.config_file_object.get('uuid', ""))
                except ValueError as e:
                    raise ValueError(
                        f"Configuration file '{self.config_path}' has invalid UUID: {e}"
                    ) from e

        if opts.task:
            task = lookup(opts.task)
            if task is None:
                alias = self.lookup_alias(opts.task)
                if alias is None:
                    raise ValueError(f"Unknown task '{opts.task}'")
                task = lookup(alias['task'])
                if task is None:
                    raise ValueError(
                        f"Unknown task '{alias['task']}' in alias '{opts.task}'"
                    )
                args += [f"--{param}" for param in alias['parameters']]
            self.task = task

        # Parse task-specific arguments.  These are of the form
        # --<task>/<param>=<value>.  At some point we want to support
        # <param>+=<value> to augment default values instead of replacing them,
        # and <param>@=<filename> to read values from a file.
        for arg in args:
            if not arg.startswith('--'):
                raise ValueError(
                    f"Task parameters must start with '--': {arg}"
                )
            arg = arg[2:]
            if '=' not in arg:
                raise ValueError(
                    f"Task parameters must be of the form --<task>/<param>=<value>: {arg}"
                )
            key, val = arg.split('=', 1)
            if '/' not in key:
                raise ValueError(
                    f"Task parameters must be of the form --<task>/<param>=<value>: {arg}"
                )
            task_name, param_name = key.split('/', 1)
            task = lookup(task_name)
            if task is None:
                raise ValueError(
                    f"Unknown task '{task_name}' in parameter '{arg}'"
                )
            param = task.get_parameter(param_name)
            if param is None:
                raise ValueError(
                    f"Task '{task_name}' has no parameter named '{param_name}'"
                )

            if task_name not in self.task_params:
                self.task_params[task_name] = {}
            self.task_params[task_name][param_name] = param.str2val(val)
            self.command_line_parameters.append(arg)

        return opts

    def lock(self):
        # Lock the configuration file to prevent concurrent modifications.
        try:
            self._locked_file = self.config_path.open('r+')
            fcntl.flock(self._locked_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RuntimeError(
                f"Could not acquire lock on configuration file '{self.config_path}': "
                "another instance of bricoler may be running"
            ) from e

    def usage(self) -> None:
        # XXX-MJ usage is not very good
        self.parser.print_usage()
