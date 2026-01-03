#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import os
from abc import abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional

from util import run_cmd


class VMImage:
    def __init__(self, path: Path, machine: str):
        self.path = path
        self.machine = machine


class VMHypervisor(Enum):
    BHYVE = 'bhyve'
    QEMU = 'qemu'


class VMRun:
    class BlockDriver(Enum):
        VIRTIO = 1,
        AHCI = 2,
        NVME = 3,

    class NetworkDriver(Enum):
        VIRTIO = 1,
        E1000 = 2,

    def __init__(
        self,
        image: VMImage,
        memory: int = 2048,
        ncpus: int = 2,
        block_driver: BlockDriver = BlockDriver.VIRTIO,
        nic_driver: NetworkDriver = NetworkDriver.VIRTIO,
    ):
        self.image = image
        self.memory = memory
        self.ncpus = ncpus
        self.block_driver = block_driver
        self.nic_driver = nic_driver

    @abstractmethod
    def setup(self) -> List[Any]: ...

    def boot(self, interactive) -> None:
        pass


class BhyveRun(VMRun):
    @staticmethod
    def access() -> bool:
        return os.access("/dev/vmmctl", os.R_OK | os.W_OK)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.image.machine.split('/')[0] not in ('amd64', 'arm64', 'i386'):
            raise ValueError(
                f"bhyve does not support machine type '{self.image.machine}'"
            )

    def block_driver_name(self) -> str:
        driver = self.block_driver
        if driver == VMRun.BlockDriver.VIRTIO:
            return "virtio-blk"
        elif driver == VMRun.BlockDriver.AHCI:
            return "ahci-hd"
        elif driver == VMRun.BlockDriver.NVME:
            return "nvme"

    def bootrom_path(self) -> Path:
        bootroms = {
            'amd64': Path('/usr/local/share/uefi-firmware/BHYVE_UEFI.fd'),
            'arm64': Path('/usr/local/share/u-boot/u-boot-bhyve-arm64/u-boot.bin'),
            'i386': Path('/usr/local/share/uefi-firmware/BHYVE_UEFI_32.fd'),
        }
        return bootroms[self.image.machine.split('/', maxsplit=1)[0]]

    def network_driver_name(self) -> str:
        driver = self.nic_driver
        if driver == VMRun.NetworkDriver.VIRTIO:
            return "virtio-net"
        elif driver == VMRun.NetworkDriver.E1000:
            return "e1000"

    def setup(self) -> List[Any]:
        destroy_cmd = ["bhyvectl", "--vm=bricoler", "--destroy"]
        run_cmd(destroy_cmd, check_result=False)

        bhyve_cmd = ["bhyve", "-c", self.ncpus, "-m", f"{self.memory}M"]
        devindex = 0

        def add_device(desc):
            nonlocal devindex
            bhyve_cmd.extend(["-s", f"{devindex}:0,{desc}"])
            devindex += 1

        add_device("hostbridge")
        if self.image.machine.startswith('amd64/') or self.image.machine.startswith('i386/'):
            bhyve_cmd.extend([
                "-H",
                "-l", "com1,stdio",
                "-l", "bootrom,{bootrom}"
            ])
            add_device("lpc")
        else:
            bhyve_cmd.extend([
                "-o", "console=stdio",
                "-o", "bootrom,{bootrom}"
            ])
        add_device(f"{self.block_driver_name()},{self.image.path}")

        bhyve_cmd.extend(["bricoler"])

        return [str(a) for a in bhyve_cmd]


class QEMURun(VMRun):
    executables = {
        'amd64': 'qemu-system-x86_64',
        'i386': 'qemu-system-i386',
        'arm': 'qemu-system-arm',
        'arm64': 'qemu-system-aarch64',
        'riscv': 'qemu-system-riscv64',
    }

    def bios_path(self) -> Path:
        bioses = {
            # XXX-MJ add some dict type which automatically checks for the path
            #        and suggests some recourse if it's not available
            'amd64': Path("/usr/local/share/edk2-qemu/QEMU_UEFI-x86_64.fd"),
            'arm64': Path("/usr/local/share/qemu/edk2-aarch64-code.fd"),
        }
        return bioses[self.image.machine.split('/', maxsplit=1)[0]]

    def block_driver_name(self) -> str:
        driver = self.block_driver
        if driver == VMRun.BlockDriver.VIRTIO:
            return "virtio-blk-pci"
        else:
            raise ValueError(
                f"Unsupported block driver {driver} is not supported by QEMU"
            )

    def machine_type(self) -> Optional[str]:
        machines = {
            'arm64': 'virt,gic-version=3',
        }
        return machines.get(self.image.machine.split('/', maxsplit=1)[0], None)

    def setup(self) -> List[Any]:
        qemu_executable = self.executables.get(self.image.machine.split('/')[0])
        if qemu_executable is None:
            raise ValueError(
                f"qemu does not support machine type '{self.image.machine}'"
            )

        qemu_cmd = [
            qemu_executable,
            "-nographic",
            "-no-reboot",
            "-cpu", "max",
            "-m", f"{self.memory}M",
            "-smp", self.ncpus,
            "-bios", self.bios_path(),
            "-device", "virtio-rng-pci",
            "-device", f"{self.block_driver_name()},drive=image",
            "-drive", f"file={self.image.path},if=none,id=image,format=raw",
        ]
        machine_type = self.machine_type()
        if machine_type is not None:
            qemu_cmd.extend(["-M", machine_type])

        return [str(a) for a in qemu_cmd]
