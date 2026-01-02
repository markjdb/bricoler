#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

#
# A task represents a composable unit of work in the bricoler framework.  They
# are all defined as a subclass of the Task class.  In general they declare
# parameters, inputs and outputs, and implement a run() method which performs
# the work of the task.
#
# Tasks can have a name or be anonymous.  Anonymous tasks are not directly
# invokable or otherwise visible in the UI, but can be used to factor out common
# functionality and parameters.
#
# Tasks can inherit from other tasks.
# XXX-MJ need some magic to compose parameters
#

import inspect
import subprocess
from abc import ABC, ABCMeta, abstractmethod
from collections import ChainMap
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple, Type

from config import Config
from util import chdir, run_cmd


class TaskMeta(ABCMeta):
    _registry: Dict[str, Type['Task']] = {}
    _reserved_names: Set[str] = {
        'bindings',
        'config',
        'description',
        'inputs',
        'name',
        'outputs',
        'parameters',
        'run',
        'skip',
    }

    @classmethod
    def _validate_common(mcs, cls: Type['Task'], namespace) -> None:
        # Task class names must end with 'Task'.
        if not cls.__name__.endswith('Task'):
            raise ValueError(
                f"Task class name '{cls.__name__}' must end with 'Task'"
            )
        # No bindings should be defined initially, they are added once we
        # instantiate tasks and bind parameters.
        if len(getattr(cls, 'bindings', {})) > 0:
            raise ValueError(
                f"Task '{cls.name}' should not define any bindings"
            )

        # Any members must be a parameter type.
        parameters = getattr(cls, 'parameters', {})
        for name in namespace.keys():
            if name.startswith('_'):
                continue
            if name in mcs._reserved_names:
                continue
            if name not in parameters:
                raise ValueError(
                    f"Member '{name}' in task '{cls.name}' is not defined as a parameter"
                )

    @classmethod
    def _validate_named_task(mcs, cls: Type['Task'], name: str, namespace) -> None:
        mcs._validate_common(cls, namespace)

        parameters = getattr(cls, 'parameters')
        inputs = getattr(cls, 'inputs')
        outputs = getattr(cls, 'outputs')

        # Do some validation of the task definition.
        #
        # Ensure that the input parameter names are disjoint.
        overlap = inputs.keys() & parameters.keys()
        if len(overlap) > 0:
            raise ValueError(
                f"Task '{name}' has overlapping names: {', '.join(overlap)}"
            )
        # Make sure that none of the names overlap with reserved names.
        overlap = (inputs.keys() & mcs._reserved_names) | \
                  (outputs.keys() & mcs._reserved_names) | \
                  (parameters.keys() & mcs._reserved_names)
        if len(overlap) > 0:
            raise ValueError(
                f"Task '{name}' uses reserved names: {', '.join(overlap)}"
            )
        # Inputs must be a subclass of Task.
        for name, input_type in inputs.items():
            if not inspect.isclass(input_type) or not issubclass(input_type, Task):
                raise TypeError(
                    f"Input '{name}' in task '{cls.name}' must be a subclass of Task"
                )
        # Validate parameter types.
        for name, param in parameters.items():
            val = getattr(cls, name, None)
            if val is not None and type(val) is not param.type:
                raise TypeError(
                    f"Parameter '{name}' in task '{cls.name}' has type "
                    f"{type(getattr(cls, name))}, expected {param.typename}"
                )

    @classmethod
    def _validate_anonymous_task(mcs, cls: Type['Task'], namespace) -> None:
        mcs._validate_common(cls, namespace)

        invalid_keys = mcs._reserved_names & set(namespace.keys())
        if len(invalid_keys) > 0:
            raise ValueError(
                f"Anonymous task '{cls.__name__}' cannot define: {', '.join(invalid_keys)}"
            )

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)

        parent_parameters = [
            b._merged_parameters for b in bases if hasattr(b, '_merged_parameters')
        ]
        cls._merged_parameters = ChainMap(cls.parameters, *parent_parameters)

        if not inspect.isabstract(cls):
            task_name = namespace.get('name')
            if task_name is not None:
                mcs._validate_named_task(cls, task_name, namespace)
                mcs._registry[task_name] = cls
            else:
                mcs._validate_anonymous_task(cls, namespace)
        return cls

    @classmethod
    def lookup(mcs, name: str) -> Optional[Type['Task']]:
        return mcs._registry.get(name)

    @classmethod
    def task_names(mcs) -> List[str]:
        return list(mcs._registry.keys())


class TaskParameter:
    choices: Optional[List[Any]] = None
    default: Any
    description: str
    _initialized = False
    required: bool
    type: Any

    def __init__(
        self,
        description: str = '',
        type: type = str,
        default: Any = None,
        choices: Optional[List[Any]] = None,
        required: bool = False,
    ):
        self.description = description
        self.type = type
        self.default = default
        self.choices = choices
        self.required = required

        if self.default is not None:
            while callable(self.default):
                self.default = self.default()
            if not isinstance(self.default, self.type):
                raise TypeError(
                    f"Default value {type(self.default)} does not match parameter type {self.type}"
                )
        self._initialized = True

    def __setattr__(self, key, value):
        if self._initialized:
            # These objects are immutable after instantiation.
            raise AttributeError(f"Cannot modify attribute '{key}' of TaskParameter")
        super().__setattr__(key, value)

    @property
    def typename(self) -> str:
        if hasattr(self.type, '__name__'):
            return self.type.__name__
        return str(self.type)

    def str2val(self, s: str) -> Any:
        if self.type is bool:
            if s.lower() in ('1', 'true', 'yes', 'on'):
                val = True
            elif s.lower() in ('0', 'false', 'no', 'off'):
                val = False
            else:
                raise ValueError(f"Value '{s}' is not of type {self.typename}")
        else:
            try:
                val = self.type(s)
            except Exception as e:
                raise ValueError(f"Value '{s}' is not of type {self.typename}") from e
        return val


class TaskParameterBinding:
    value: Any
    source: 'TaskParameterBinding.BindingType'
    task: Optional[str]

    class BindingType(Enum):
        DEFAULT = 1,
        COMMAND_LINE = 2,
        OVERRIDDEN = 3,

    def __init__(self, value, source: BindingType, task=None):
        self.value = value
        self.source = source
        self.task = task

    def __str__(self) -> str:
        return str(self.value)


class Task(ABC, metaclass=TaskMeta):
    bindings: Dict[str, TaskParameterBinding]
    config: Config
    _final_outputs: Optional[Dict[str, Any]] = None
    name: str
    description: str = ''
    inputs: Dict[str, Type['Task']] = {}
    outputs: Dict[str, Any] = {}
    parameters: Dict[str, TaskParameter] = {}
    _merged_parameters: ChainMap[str, TaskParameter]
    skip: bool = False

    def __init__(self, config: Config):
        super().__init__()
        self.bindings = {}
        self.config = config
        self._finished = False

        for name, param in self._merged_parameters.items():
            self.bind({name: param.default},
                      TaskParameterBinding.BindingType.DEFAULT)
        for name, val in self.__class__.__dict__.items():
            if name in self._merged_parameters:
                self.bind({name: val},
                          TaskParameterBinding.BindingType.OVERRIDDEN)

    def bind(self, params: Dict[str, Any], source: TaskParameterBinding.BindingType) -> None:
        for name, param in params.items():
            if name not in self._merged_parameters:
                raise ValueError(
                    f"Task '{self.name}' has no parameter named '{name}'"
                )
            self.bindings[name] = TaskParameterBinding(value=param, source=source)

    @classmethod
    def get_parameter(self, name: str) -> TaskParameter:
        return self._merged_parameters[name]

    def get_parameter_keys(self) -> List[str]:
        return list(self._merged_parameters.keys())

    def _run(self, ctx: SimpleNamespace) -> Dict[str, Any]:
        if self._final_outputs is not None:
            # Each task runs only once.
            return self._final_outputs

        for name, param in self.bindings.items():
            setattr(self, name, param.value)

        with chdir(Path.cwd() / self.name):
            outputs = self.run(ctx)
            if set(outputs.keys()) != set(self.outputs.keys()):
                missing = set(self.outputs.keys()) - set(outputs.keys())
                raise ValueError(
                    f"Task {self.name} did not produce expected outputs: {', '.join(missing)}"
                )
            for name, val in outputs.items():
                # It would be nice if we could validate this statically...
                expected_type = self.outputs[name]
                if not isinstance(val, expected_type):
                    raise TypeError(
                        f"Output '{name}' in task '{self.name}' has type "
                        f"{type(val)}, expected {expected_type}"
                    )
            self._final_outputs = outputs
            return outputs

    def run_cmd(self, cmd: List[Any], *args, **kwargs) -> subprocess.CompletedProcess:
        return run_cmd(cmd, *args, skip=self.skip, **kwargs)

    @abstractmethod
    def run(self, ctx) -> Dict[str, Any]: ...


class TaskSchedule:
    class TaskScheduleNode:
        task: Task
        children: Dict[str, 'TaskSchedule.TaskScheduleNode']

        def __init__(self, task: Type[Task], config: Config):
            self.task = task(config)
            self.children = {}
            for name, input in task.inputs.items():
                self.children[name] = TaskSchedule.TaskScheduleNode(input, config)

        def _run(self, ctx: SimpleNamespace) -> Dict[str, Any]:
            for input, child in self.children.items():
                outputs = child._run(ctx)
                inputs = {}
                for name, val in outputs.items():
                    inputs[name] = val
                setattr(self.task, input, SimpleNamespace(**inputs))
            return self.task._run(ctx)

        def __iter__(self):
            yield self
            for child in self.children.values():
                yield from child

    config: Config
    schedule: TaskScheduleNode

    def __init__(self, config: Config):
        self.config = config
        self.schedule = self.TaskScheduleNode(config.task, config)

        # Preen the schedule.  We only keep one instance of each task.
        tasks: Dict[str, Task] = {}
        for node in self.schedule:
            if node.task.name in tasks:
                node.task = tasks[node.task.name]
            else:
                tasks[node.task.name] = node.task

        # Bind command-line parameters.
        params = config.task_params.copy()
        for node in self.schedule:
            if node.task.name in params:
                node.task.bind(
                    params[node.task.name],
                    TaskParameterBinding.BindingType.COMMAND_LINE
                )
                del params[node.task.name]
        if len(params) > 0:
            unknown_tasks = ', '.join(params.keys())
            raise ValueError(
                f"Unknown tasks in command-line parameters: {unknown_tasks}"
            )

        # Mark dependent tasks to be skipped.
        if self.config.skip:
            for node in self.schedule:
                if node != self.schedule:
                    node.task.skip = True

    def run(self):
        # Do any tasks have unbound required parameters?  Raise an error if so.
        # We check this here rather than in the constructor so that it's possible
        # to do things like list unbound parameters in a schedule.
        for node in self.schedule:
            required = {
                name for name, param in node.task._merged_parameters.items() if param.required
            }
            bindings = {
                name for name, param in node.task.bindings.items() if param.value is not None
            }
            missing = required - bindings
            if len(missing) > 0:
                raise ValueError(
                    f"Task '{node.task.name}' is missing required parameters: {', '.join(missing)}"
                )

        ctx = SimpleNamespace(max_jobs=self.config.max_jobs)
        with chdir(self.config.workdir):
            self.schedule._run(ctx)

    @property
    def parameters(self) -> Dict[str, Tuple[TaskParameter, Any]]:
        """Return a mapping of parameter names to their values in the schedule."""
        result: Dict[str, Any] = {}

        def _collect(node: TaskSchedule.TaskScheduleNode):
            for name in node.task._merged_parameters.keys():
                val = node.task.bindings.get(name, None)
                result[f"{node.task.name}/{name}"] = (
                    node.task._merged_parameters[name], val
                )

            for child in node.children.values():
                _collect(child)

        _collect(self.schedule)
        return result

    @property
    def tasks(self) -> Dict[str, Task]:
        """Return a mapping of task names to task instances in the schedule."""
        result: Dict[str, Task] = {}

        def _collect(node: TaskSchedule.TaskScheduleNode):
            result[node.task.name] = node.task
            for child in node.children.values():
                _collect(child)

        _collect(self.schedule)
        return result

    @property
    def target(self) -> Task:
        """Return the target task of the schedule."""
        return self.schedule.task
