#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import functools
import json
import os
import re
import shutil
import sys
import textwrap
import time
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type, Union

from .config import Config
from .git import GitRepository
from .mtree import MtreeFile
from .task import Task, TaskParameter, TaskMeta, TaskSchedule
from .util import chdir, host_machine, info, run_cmd, warn
from .vm import FreeBSDVM, VMImage, VMHypervisor, BhyveRun, QEMURun


class FreeBSDSrcRepository(GitRepository):
    @functools.cache
    def get___FreeBSD_version(self) -> int:
        file = self.path / 'sys' / 'sys' / 'param.h'
        with file.open('r') as f:
            pattern = re.compile(r'^\s*#define\s+__FreeBSD_version\s+(\d+)')
            for line in f:
                match = pattern.match(line)
                if match:
                    return int(match.group(1))
            raise ValueError(
                f"Could not obtain __FreeBSD_version from {file}"
            )

    def make(self, args: List[str], **kwargs):
        cmd = ['make', '-C', self.path.resolve()] + args
        # Don't skip the command if we need to capture output.
        skip = self._no_cmds and not kwargs.get('capture_output', False)
        return run_cmd(cmd, skip=skip, **kwargs)

    @functools.cache
    def machine_targets(self) -> List[str]:
        pattern = re.compile(r'^\s*\w+/\w+$')
        output = self.make(['targets'], capture_output=True).stdout.decode()
        targets = []
        for line in output.splitlines():
            if pattern.match(line.strip()):
                targets.append(line.strip())
        return targets


class GitCheckoutTask(Task):
    """
    Clone a git repository, or update an existing clone.

    Alternately, pass a filesystem path for the "url" parameter instead
    of a URL or ssh address to use an existing local clone.
    """
    name = "git-checkout"

    parameters = {
        'url': TaskParameter(
            description="URL of the Git repository to clone, or a filesystem path",
            required=True,
        ),
        'branch': TaskParameter(
            description="Branch to check out",
        ),
    }
    outputs = {
        'repo': GitRepository
    }

    def run(self, ctx, repotype: Type[GitRepository] = GitRepository):
        repo = repotype(self.url, Path("./src"), self.branch, no_cmds=self.skip)
        repo.update()
        return {'repo': repo}


class FreeBSDSrcGitCheckoutTask(GitCheckoutTask):
    """
    Clone the FreeBSD src tree, or update an existing clone.
    """
    name = "freebsd-src-git-checkout"

    url = "anongit@git.freebsd.org:src.git"
    branch = "main"

    outputs = {
        'repo': FreeBSDSrcRepository,
        'FreeBSD_version': int,
    }

    def run(self, ctx):
        outputs = super().run(ctx, repotype=FreeBSDSrcRepository)
        outputs['FreeBSD_version'] = outputs['repo'].get___FreeBSD_version()
        return outputs


class FreeBSDSrcBuildTask(Task):
    """
    Build a FreeBSD source tree.  On its own this does nothing, the invoker
    needs to specify some build targets.
    """
    name = "freebsd-src-build"

    parameters = {
        'clean': TaskParameter(
            description="Clean build directories before building",
            type=bool,
            default=False,
        ),
        'kernel_config': TaskParameter(
            description="Kernel configuration to build",
            default="GENERIC",
        ),
        'machine': TaskParameter(
            description="Target machine architecture",
            default=host_machine(),
        ),
        'make_options': TaskParameter(
            description="Additional make(1) options to pass to the build",
            type=str,  # XXX-MJ List[str]
        ),
        'make_targets': TaskParameter(
            description="Make targets to build",
            type=str,  # XXX-MJ List[str]
            default=''
        ),
        'objdir': TaskParameter(
            description="Object directory path for the build",
            type=Path,  # XXX-MJ default must be computed after some partial eval
        ),
        'toolchain': TaskParameter(
            description="Toolchain to use for the build",
        ),
    }

    inputs = {
        'src': FreeBSDSrcGitCheckoutTask,
    }

    outputs = {
        'machine': str,
        'metalog': MtreeFile,
        'stagedir': Path,
    }

    def run(self, ctx):
        # See if the user specified a valid target platform.
        if '/' not in self.machine:
            machine = self.machine
            machine_arch = ''
        else:
            (machine, machine_arch) = self.machine.split('/', maxsplit=1)
        targets = self.src.repo.machine_targets()
        if machine_arch == '':
            matches = [target for target in targets if target.startswith(f"{machine}/")]
            if len(matches) == 1:
                machine_arch = matches[0].split('/', maxsplit=1)[1]
            else:
                raise ValueError(
                    f"Multiple architectures found for machine '{machine}': {' '.join(matches)}'"
                )
        if f"{machine}/{machine_arch}" not in targets:
            raise ValueError(
                f"Unknown target platform: {self.machine}"
            )

        objdir = self.objdir
        if objdir is None:
            objdir = Path(f"./obj.{machine}.{machine_arch}").resolve()
        objdir.mkdir(parents=True, exist_ok=True)

        stagedir = Path(f"./stage.{machine}.{machine_arch}").resolve()
        stagedir.mkdir(parents=True, exist_ok=True)

        mtree = MtreeFile()
        for target in self.make_targets.split():
            metalog = stagedir / f"METALOG.{target}.mtree"
            if not self.skip:
                with open(metalog, 'w') as f:
                    f.truncate(0)

            args = [
                target,
                "-ss",
                "-j", ctx.max_jobs,
                "-DNO_ROOT",
                f"DESTDIR={stagedir}",
                f"METALOG={metalog}",
                f"TARGET={machine}",
                f"TARGET_ARCH={machine_arch}",
                f"KERNCONF={self.kernel_config}",
            ]
            if self.clean:
                args.append("WITH_CLEAN=")
            else:
                args.append("WITHOUT_CLEAN=")
            if self.toolchain is not None:
                args.append(f"CROSS_TOOLCHAIN={self.toolchain}")
            if self.make_options is not None:
                args += self.make_options.split()

            env = {
                "MAKEOBJDIRPREFIX": objdir,
                "SRCCONF": "/dev/null",
                "__MAKE_CONF": "/dev/null",
            }

            self.src.repo.make(args, env=env)

            mtree.load(metalog, append=True, contents_root=stagedir)

        return {
            'machine': f"{machine}/{machine_arch}",
            'metalog': mtree,
            'stagedir': stagedir,
        }


class FreeBSDSrcBuildAndInstallTask(FreeBSDSrcBuildTask):
    make_targets = "buildworld buildkernel installworld installkernel distribution"


class FreeBSDPkgBaseBuildTask(FreeBSDSrcBuildTask):
    make_targets = "buildworld buildkernel packages"


class FreeBSDVMImageFilesystem(Enum):
    UFS = 'ufs'
    ZFS = 'zfs'


class FreeBSDVMImageTask(Task):
    """
    Build a FreeBSD VM image, optionally adding an overlay tree, installing
    packages, and applying other customizations.
    """
    name = "freebsd-vm-image"

    inputs = {
        'src': FreeBSDSrcGitCheckoutTask,
        'build': FreeBSDSrcBuildAndInstallTask,
    }

    outputs = {
        'image': VMImage,
        'ssh_key': Path,
        'sysroot': Path,
    }

    parameters = {
        'filesystem': TaskParameter(
            description="Filesystem type for the VM image",
            type=FreeBSDVMImageFilesystem,  # XXX-MJ validate enum
            default=FreeBSDVMImageFilesystem.UFS,
        ),
        'hostname': TaskParameter(
            description="Hostname for the VM",
            default='freebsd',
        ),
        'image_size': TaskParameter(
            description="Size of the filesystem image in GiB",
            type=int,
            default=10,
        ),
        'loader_tunables': TaskParameter(
            description="Loader tunables for the VM",
            type=str,  # XXX-MJ Dict[str, str]
            default='',
        ),
        'overlay': TaskParameter(
            description="Path to an overlay directory to copy into the image",
            type=Path,
        ),
        'packages': TaskParameter(
            description="A list of packages to install into the image",
        ),
        'package_repo_file': TaskParameter(
            description="Path to a pkg(8) repository configuration file used to fetch packages",
            type=Path,
            # XXX-MJ should be a default
        ),
        'rc_kld_list': TaskParameter(
            description="A list of kernel modules to load at boot time",
        ),
        'swap_size': TaskParameter(
            description="Size of the swap partition",
            default="2G",
        ),
        'sysctls': TaskParameter(
            description="A list of sysctl(8) settings to apply to the image",
            type=str,  # XXX-MJ Dict[str, str]
        ),
    }

    def run(self, ctx):
        machine = self.build.machine
        metalog: MtreeFile = self.build.metalog
        stagedir = self.build.stagedir
        zfs_pool_name = "zroot"

        outputs = {}

        # Create ssh keys for the VM.
        with chdir(Path("./ssh-keys")):
            keyfile = Path.cwd() / "id_ed25519_root"
            if not keyfile.is_file():
                self.run_cmd(["ssh-keygen", "-t", "ed25519", "-f", str(keyfile), "-N", ""])
            metalog.add_file(keyfile.with_suffix('.pub'),
                             Path("root/.ssh/authorized_keys"))
            outputs['ssh_key'] = keyfile

        def add_overlay(root: Path) -> None:
            if not root.is_dir():
                raise ValueError(f"Overlay path '{root}' is not a directory")
            for item in root.rglob('*'):
                rel = item.relative_to(root)
                if item.is_dir():
                    metalog.add_dir(rel)
                elif item.is_file():
                    metalog.add_file(item, rel)
                else:
                    warn(f"Skipping unsupported overlay item: {item}")

        def add_config_file(
            _path: Union[Path, str],
            *args,
            source: Optional[Path] = None,
            comment_delimiter: str = "#",
        ) -> None:
            if self.skip:
                return
            path = Path(_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if source is not None:
                shutil.copyfile(source, path)
                mode = "a"
            else:
                mode = "w"
            with path.open(mode) as f:
                f.write(f"{comment_delimiter} Added by bricoler\n")
                contents = [textwrap.dedent(arg).strip() for arg in args if arg != ""]
                f.write(str.join("\n", contents) + "\n")
            metalog.add_file(path.resolve(), path)

        if self.overlay is not None:
            add_overlay(self.overlay)

        add_config_file("etc/ssh/sshd_config",
                        "PermitRootLogin without-password",
                        source=(stagedir / "etc/ssh/sshd_config"))

        if self.rc_kld_list is not None:
            kld_list = self.rc_kld_list.split()
        else:
            kld_list = []
        add_config_file("etc/rc.conf",
                        f"hostname={self.hostname}",
                        "ifconfig_vtnet0=SYNCDHCP",
                        "ifconfig_em0=SYNCDHCP",
                        "defaultroute_delay=2",
                        "sshd_enable=YES",
                        "sshd_rsa_enable=NO",
                        *[f"kld_list=\"${{kld_list}} {kld}\"" for kld in kld_list],
                        f"""
                        zfs_enable=YES
                        zpool_reguid={zfs_pool_name}
                        zpool_upgrade={zfs_pool_name}
                        """ if self.filesystem == FreeBSDVMImageFilesystem.ZFS else "")

        add_config_file("etc/fstab",
                        """
                        /dev/gpt/rootfs / ufs rw 1 1
                        """ if self.filesystem == FreeBSDVMImageFilesystem.UFS else "",
                        "none /dev/fd fdescfs rw 0 0")

        add_config_file("boot/loader.conf",
                        "autoboot_delay=1",
                        "beastie_disable=YES",
                        "loader_logo=none",
                        "console=comconsole",
                        "kern.geom.label.disk_ident.enable=0",
                        "zfs_load=YES" if self.filesystem == FreeBSDVMImageFilesystem.ZFS else "",
                        *[tunable for tunable in self.loader_tunables.split()])

        if self.sysctls is not None:
            add_config_file("etc/sysctl.conf",
                            *[sysctl for sysctl in self.sysctls.split()],
                            source=(stagedir / "etc/sysctl.conf"))

        add_config_file("firstboot")

        if self.packages is not None:
            major = self.src.FreeBSD_version // 100000
            pkgabi = f"FreeBSD:{major}:{machine.split('/')[1]}"

            pkg_root = Path.cwd() / "pkg" / pkgabi
            cache_dir = pkg_root / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_dir = pkg_root / "db"
            db_dir.mkdir(parents=True, exist_ok=True)
            repos_dir = pkg_root / "repo"
            repos_dir.mkdir(parents=True, exist_ok=True)

            # Set up a pkg repository configuration.
            if self.package_repo_file is None:
                with resources.as_file(resources.files("bricoler") / "pkg.conf") as src:
                    shutil.copyfile(src, repos_dir / "pkg.conf")
            else:
                shutil.copyfile(self.package_repo_file, repos_dir / "pkg.conf")

            def pkg_cmd(*args, **kwargs):
                cmd = [
                    "pkg",
                    "-o", "ASSUME_ALWAYS_YES=true",
                    "-o", "INSTALL_AS_USER=yes",
                    "-o", f"ABI={pkgabi}",
                    "-o", f"PKG_CACHEDIR={cache_dir}",
                    "-o", f"PKG_DBDIR={db_dir}",
                    "-o", f"OSVERSION={self.src.FreeBSD_version}",
                    "-o", f"REPOS_DIR={repos_dir}",
                ]
                cmd += list(args)
                return self.run_cmd(cmd, **kwargs)

            stage_dir = pkg_root / "stage"
            pkg_reldir = "root/pkg"
            pkg_dir = stage_dir / pkg_reldir
            pkg_dir.mkdir(parents=True, exist_ok=True)
            pkg_cmd("update")
            pkg_cmd("fetch", "--dependencies", "-o", pkg_dir, "pkg", *self.packages.split())
            pkg_cmd("repo", pkg_dir)

            pkg_version = pkg_cmd("rquery", "%v", "pkg", capture_output=True).stdout
            pkg_version = pkg_version.decode().strip()

            add_overlay(stage_dir)

            add_config_file("etc/pkg/local.conf",
                            f"""
                            local: {{
                                url: "file:///{pkg_reldir}",
                                signature_type: "none",
                            }}
                            """)

            add_config_file("etc/rc.local",
                            f"""
                            bricoler_add_pkgs()
                            {{
                                export PATH=${{PATH}}:/usr/local/sbin:/usr/local/bin
                                echo ""
                                echo "bricoler: Running first-boot setup"
                                # Older version of pkg(7) don't use basename().
                                cd /{pkg_reldir}/All
                                # Install pkg(8).
                                IGNORE_OSVERSION=yes pkg add -r local pkg-{pkg_version}*
                                # Install the requested packages.
                                IGNORE_OSVERSION=yes pkg install -y -r local {self.packages}
                            }}

                            if [ -f /firstboot ]; then
                                bricoler_add_pkgs
                            fi
                            """)

        metalog_path = Path.cwd() / "METALOG.mtree"
        metalog.write(metalog_path)

        image_prefix = f"image.{self.build.machine.replace('/', '.')}"
        esp_image_path = Path.cwd() / f"{image_prefix}-esp.fs"
        fs_image_path = Path.cwd() / f"{image_prefix}.{self.filesystem.value}"
        vm_image_path = Path.cwd() / f"{image_prefix}.img"

        makefs_cmd = ["makefs"]
        if self.filesystem == FreeBSDVMImageFilesystem.UFS:
            makefs_cmd += [
                "-t", "ffs",
                "-Z",
                "-o", "softupdates=1",
                "-o" "version=2"
            ]
        else:
            makefs_cmd += [
                "-t", "zfs",
                "-o", f"poolname={zfs_pool_name}",
                "-o", f"bootfs={zfs_pool_name}"
            ]
        makefs_cmd += [
            "-DD",
            "-s", f"{self.image_size}g",
            fs_image_path,
            metalog_path,
        ]

        with chdir(stagedir):
            self.run_cmd(makefs_cmd)

        has_efi = not (machine.startswith('i386/') or machine.startswith('powerpc/'))
        if has_efi:
            efi_loaders = {
                'amd64': "bootx64.efi",
                'arm': "bootarm.efi",
                'arm64': "bootaa64.efi",
                'riscv': "bootriscv64.efi",
            }
            esp_dir = Path(image_prefix + "-efi")
            shutil.rmtree(esp_dir, ignore_errors=True)
            with chdir(esp_dir / "EFI/BOOT"):
                efi_loader = efi_loaders[machine.split('/')[0]]
                shutil.copyfile(stagedir / "boot/loader.efi", Path(efi_loader))

            makefs_cmd = [
                "makefs",
                "-t", "msdos",
                "-o", "fat_type=16",
                "-o", "sectors_per_cluster=1",
                "-o", "volume_label=EFI",
                "-s", "4m",
                esp_image_path,
                esp_dir,
            ]
            self.run_cmd(makefs_cmd)

        bootdir = stagedir / "boot"
        mkimg_cmd = [
            "mkimg",
            "-f", "raw",
            "-S", 512,
            "-o", vm_image_path,
        ]
        if machine.startswith('powerpc/'):
            mkimg_cmd += [
                "-s", "mbr",
                "-a", "1",
                "-p", f"prepboot:={bootdir / 'boot1.elf'}"
                "-p", f"freebsd:={vm_image_path}",
            ]
        else:
            mkimg_cmd += ["-s", "gpt"]
            if machine.startswith('amd64/') or machine.startswith('i386/'):
                mkimg_cmd += [
                    "-b", f"{bootdir / 'pmbr'}",
                    "-p", f"freebsd-boot/bootfs:={bootdir / 'gptboot'}",
                ]
            if has_efi:
                mkimg_cmd += [
                    "-p", f"efi:={esp_image_path}",
                ]
            mkimg_cmd += [
                "-p", f"freebsd-swap/swap::{self.swap_size}",
                "-p", f"freebsd-{self.filesystem.value}/rootfs:={fs_image_path}",
            ]

        self.run_cmd(mkimg_cmd)

        outputs['image'] = VMImage(vm_image_path, machine)
        outputs['sysroot'] = stagedir

        return outputs


class FreeBSDVMBootTask(Task):
    """
    Boot a FreeBSD VM image using QEMU or bhyve.

    In interactive mode, the VM console is provided on standard stdin/stdout,
    and this task does not return until the VM exits.  In non-interactive mode,
    bricoler owns the console and can interact with it
    """
    name = "freebsd-vm-boot"

    inputs = {
        'vm_image': FreeBSDVMImageTask,
    }

    parameters = {
        'hypervisor': TaskParameter(
            description="Hypervisor to use for running the VM",
            type=VMHypervisor,
            default=lambda: VMHypervisor.BHYVE if BhyveRun.access() else VMHypervisor.QEMU,
        ),
        'interactive': TaskParameter(
            description="Run the VM in interactive mode",
            type=bool,
            default=True,
        ),
        'memory': TaskParameter(
            description="Amount of memory to allocate to the VM in MiB",
            default=2048,
            type=int,
        ),
        'ncpus': TaskParameter(
            description="Number of CPUs to allocate to the VM",
            type=int,
            default=2,
        ),
        'reboot': TaskParameter(
            description="Restart the VM when it exits due to a reboot",
            type=bool,
            default=False,
        ),
    }

    outputs = {
        'vm': Optional[FreeBSDVM],
    }

    def run(self, ctx):
        cls = QEMURun if self.hypervisor == VMHypervisor.QEMU else BhyveRun
        vmrun = cls(
            image=self.vm_image.image,
            memory=self.memory,
            ncpus=self.ncpus,
        )

        # Save ssh and gdb addresses for later use.
        with open(Path.cwd() / "gdb-addr", "w") as f:
            f.write(f"{vmrun.gdb_addr[0]}:{vmrun.gdb_addr[1]}")
        with open(Path.cwd() / "ssh-addr", "w") as f:
            f.write(f"{vmrun.ssh_addr[0]}:{vmrun.ssh_addr[1]}")
        # Symlink the ssh key as well.
        ssh_key_dest = Path.cwd() / "ssh_key"
        ssh_key_dest.unlink(missing_ok=True)
        ssh_key_dest.symlink_to(self.vm_image.ssh_key)
        # Symlink the staging directory so that we can easily find kernel symbols.
        sysroot = Path.cwd() / "sysroot"
        sysroot.unlink(missing_ok=True)
        sysroot.symlink_to(self.vm_image.sysroot)

        cmd = vmrun.setup()
        if self.interactive:
            self.run_cmd(cmd)
            vm = None
        else:
            vm = FreeBSDVM(cmd)

        return {'vm': vm}

    def _gdb(self, *args):
        if shutil.which("gdb") is None:
            raise ValueError("gdb is not available")
        sysroot = Path(os.readlink(Path.cwd() / "sysroot"))
        with open(Path.cwd() / "gdb-addr", "r") as f:
            addr = f.read().strip()
        (host, portstr) = addr.split(':', maxsplit=1)
        port = int(portstr)
        gdb_cmd = [
            "gdb",
            "-ex", f"set sysroot {Path.cwd() / sysroot}",
            "-ex", f"file {sysroot / 'boot/kernel/kernel'}",
            "-ex", f"source {sysroot / 'usr/lib/debug/boot/kernel/kernel-gdb.py'}",
            "-ex", f"target remote {host}:{port}",
        ]
        self.run_cmd(gdb_cmd)

    def _ssh(self, *args):
        with open(Path.cwd() / "ssh-addr", "r") as f:
            addr = f.read().strip()
        (host, portstr) = addr.split(':', maxsplit=1)
        port = int(portstr)
        ssh_cmd = [
            "ssh",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=no",
            "-p", port,
            "-i", Path.cwd() / "ssh_key",
            "root@" + host,
        ]
        self.run_cmd(ssh_cmd)

    actions = {
        'gdb': _gdb,
        'ssh': _ssh,
    }


class FreeBSDRegressionTestSuiteBuildTask(FreeBSDSrcBuildAndInstallTask):
    make_options = " ".join([
        # Remove some optional components to speed up the build.
        "WITHOUT_CLANG=", "WITHOUT_LLD=", "WITHOUT_LLDB=", "WITHOUT_LIB32=",
        # The in-tree ZFS tests take a long time to run and aren't very useful
        # outside of ZFS development.
        "WITHOUT_ZFS_TESTS=",
    ])

    def run(self, ctx):
        outputs = super().run(ctx)

        # Manually install the run-kyua helper script.
        dest = outputs['stagedir'] / "usr/tests/run-kyua"
        with resources.as_file(resources.files("bricoler") / "run-kyua") as src:
            shutil.copyfile(src, dest)
        outputs['metalog'].add_file(dest, Path("usr/tests/run-kyua"), mode=0o755)
        return outputs


class FreeBSDRegressionTestSuiteVMImageTask(FreeBSDVMImageTask):
    loader_tunables = " ".join([
        "net.inet.ip.fw.default_to_accept=1",
        "net.inet.ipf.jail_allowed=1",
        "net.fibs=8",
    ])

    packages = " ".join([
        "coreutils",
        "filesystems/ext2",
        "gdb",
        "git-lite",
        "gtar",
        "isc-dhcp44-server",
        "jq",
        "ksh93",
        "llvm",
        "ndisc6",
        "net/py-dpkt",
        "net/tcptestsuite",
        "nist-kat",
        "nmap",
        "openvpn",
        "perl5",
        "porch",
        "python",
        "python3",
        "devel/py-pytest",
        "devel/py-twisted",
        "net/scapy",
        "security/setaudit",
        "sg3_utils",
        "sudo",
    ])

    rc_kld_list = " ".join([
        "accf_data", "accf_dns", "accf_http", "accf_tls",
        "blake2",
        "carp",
        "cfiscsi",
        "cryptodev",
        "ctl",
        "dummymbuf",
        "dummynet",
        "fusefs",
        "if_bridge", "if_enc", "if_epair", "if_ovpn", "if_stf",
        "ipdivert",
        "ipfw", "ipfw_nat",
        "ipl",
        "ipsec",
        "mac_bsdextended", "mac_ipacl", "mac_portacl", "mqueuefs",
        "pf", "pflog", "pflow", "pfsync",
        "sctp",
        "snd_dummy",
        "tarfs",
        "tcpmd5",
        "unionfs",
        "zfs",
    ])

    sysctls = " ".join([
        "kern.ipc.tls.enable=1",
        "vfs.aio.enable_unsafe=1",
        "kern.crypto.allow_soft=1",
        "vm.panic_on_oom=1",
        "security.mac.bsdextended.enabled=0",
        "security.mac.ipacl.ipv4=0",
        "security.mac.ipacl.ipv6=0",
        "security.mac.portacl.enabled=0",
    ])

    inputs = {
        'build': FreeBSDRegressionTestSuiteBuildTask,
    }


class FreeBSDRegressionTestSuiteTask(FreeBSDVMBootTask):
    """
    Boot a virtual machine and run the FreeBSD regression test suite.
    """
    name = "freebsd-regression-test-suite"

    # XXX-MJ kernel_config should be GENERIC-DEBUG on stable branches
    interactive = False
    ncpus = os.cpu_count() // 2
    memory = 1024 * (os.cpu_count() // 2)

    inputs = {
        'vm_image': FreeBSDRegressionTestSuiteVMImageTask,
    }

    parameters = {
        'count': TaskParameter(
            description="Number of times to run the tests",
            type=int,
            default=1,
        ),
        'parallelism': TaskParameter(
            description="Number of tests to run in parallel",
            type=int,
            default=os.cpu_count() // 2,  # XXX-MJ duplicating the ncpus value
        ),
        'tests': TaskParameter(
            description="A space-separated list of test cases or test suites to run, "
                        "or the empty string to run all tests",
            default="",
        ),
    }

    def run(self, ctx):
        outputs = super().run(ctx)
        vm: FreeBSDVM = outputs['vm']
        if vm is None:
            raise ValueError(
                "Cannot run tests, VM must be run in non-interactive mode"
            )

        try:
            vm.boot_to_login()
            cmd = [
                "/usr/tests/run-kyua",
                "-c", str(self.count),
                "-j", str(self.parallelism),
                "-r", "/root/kyua.db",
                self.tests
            ]
            vm.sendline(" ".join(cmd))
            vm.wait_for_prompt(timeout=10*3600)
        except FreeBSDVM.PanicException as e:
            # XXX-MJ should optionally attach gdb to the guest here
            raise e
        return outputs


class FreeBSDDTraceTestSuiteBuildTask(FreeBSDRegressionTestSuiteBuildTask):
    make_options = FreeBSDRegressionTestSuiteBuildTask.make_options + " WITH_DTRACE_TESTS="


class FreeBSDDTraceTestSuiteVMImageTask(FreeBSDRegressionTestSuiteVMImageTask):
    packages = " ".join([
        "binutils",
        "jq",
        "libxml2",
        "llvm",
        "nmap",
        "pdksh",
        "perl5",
    ])

    rc_kld_list = " ".join([
        "dtraceall",
        "dtrace_test",
        "kinst",
        "sctp"
    ])

    inputs = {
        'build': FreeBSDDTraceTestSuiteBuildTask,
    }


class FreeBSDDTraceTestSuiteTask(FreeBSDRegressionTestSuiteTask):
    """
    Boot a virtual machine and run the FreeBSD DTrace regression test suite.
    """
    name = "freebsd-dtrace-test-suite"

    parallelism = 1
    tests = "cddl/usr.sbin/dtrace"

    inputs = {
        'vm_image': FreeBSDDTraceTestSuiteVMImageTask,
    }


class CheriBSDSrcGitCheckoutTask(FreeBSDSrcGitCheckoutTask):
    name = "cheribsd-src-git-checkout"

    url = "https://github.com/CTSRD-CHERI/cheribsd"
    branch = "dev"


class CheriBSDSrcBuildTask(FreeBSDSrcBuildTask):
    name = "cheribsd-src-build"

    machine = "arm64/aarch64c"
    toolchain = "llvm-morello"
    kernel_config = "GENERIC-MORELLO-PURECAP"

    inputs = {
        'src': CheriBSDSrcGitCheckoutTask,
    }


class CheriBSDSrcBuildAndInstallTask(CheriBSDSrcBuildTask):
    make_targets = FreeBSDSrcBuildAndInstallTask.make_targets


class CheriBSDVMImageTask(FreeBSDVMImageTask):
    name = "cheribsd-vm-image"

    inputs = {
        'src': CheriBSDSrcGitCheckoutTask,
        'build': CheriBSDSrcBuildAndInstallTask,
    }


class CheriBSDVMBootTask(FreeBSDVMBootTask):
    name = "cheribsd-vm-boot"

    inputs = {
        'vm_image': CheriBSDVMImageTask,
    }


class EC2Provider:
    config: Config
    ssh_key_dir: Path

    def __init__(self, config: Config, region: str):
        # Lazy import since this takes a bit of time (~130ms on a Zen 4).
        try:
            import boto3
        except ImportError as e:
            raise ImportError("boto3 is required for EC2 tasks") from e

        self.config = config
        self.client = boto3.client('ec2', region)
        self.resource = boto3.resource('ec2', region)
        self.ssh_key_dir = self.config.workdir / "ec2-ssh-keys"

    def create_ssh_keypair(self, key_name: str, tag_value: str) -> Path:
        with chdir(self.ssh_key_dir):
            keyfile = Path(f"{key_name}.pem").resolve()
            if not keyfile.is_file():
                key_pair = self.resource.create_key_pair(
                    KeyName=key_name,
                    TagSpecifications=[{
                        'ResourceType': "key-pair",
                        'Tags': [
                            {'Key': "bricoler", 'Value': tag_value},
                        ],
                    }]
                )
                private_key = key_pair.key_material
                with keyfile.open('w', encoding='utf-8') as f:
                    f.write(private_key)
                keyfile.chmod(0o400)
            return keyfile

    def create_instance(
        self,
        image_id: str,
        instance_type: str,
        key_name: str,
        volume_size: int,
        tag_value: str,
    ):
        ami = self.ami_by_id(image_id)
        bdm = ami.get('BlockDeviceMappings')
        bdm[0]['Ebs']['VolumeSize'] = volume_size

        instances = self.resource.create_instances(
            ImageId=image_id,
            InstanceType=instance_type,
            KeyName=key_name,
            MinCount=1,
            MaxCount=1,
            BlockDeviceMappings=bdm,
            TagSpecifications=[{
                'ResourceType': "instance",
                'Tags': [{'Key': "bricoler", 'Value': tag_value}],
            }]
        )
        instance = instances[0]
        instance.wait_until_running()
        instance.reload()

        timeout = 300
        info(f"Waiting up to {timeout} seconds for instance {instance.id} to become ready")
        start_time = time.time()
        ec2_client = instance.meta.client
        while time.time() - start_time < timeout:
            response = ec2_client.describe_instance_status(
                InstanceIds=[instance.id],
                IncludeAllInstances=False
            )

            if response['InstanceStatuses']:
                status = response['InstanceStatuses'][0]
                instance_status = status['InstanceStatus']['Status']
                system_status = status['SystemStatus']['Status']

                if instance_status == "ok" and system_status == "ok":
                    # XXX-MJ also need to wait for ssh
                    return instance
            time.sleep(5)
        raise TimeoutError(f"Instance not ready after {timeout} seconds")

    def clean(self, tag_value: str = "*"):
        filters = [
            {'Name': "tag:bricoler", 'Values': [tag_value]},
        ]

        shutil.rmtree(self.ssh_key_dir, ignore_errors=True)
        for key_pair in self.resource.key_pairs.filter(Filters=filters):
            key_pair.delete()

        instances = self.resource.instances.filter(Filters=filters)
        for instance in instances:
            instance.terminate()
        for instance in instances:
            instance.wait_until_terminated()

    @functools.cache
    def ami_by_id(self, image_id: str) -> Dict[str, str]:
        response = self.client.describe_images(ImageIds=[image_id])
        images = response['Images']
        if len(images) == 0:
            raise ValueError(f"AMI {image_id} not found")
        return images[0]

    @functools.cache
    def freebsd_amis(self, owners: Tuple[str] = ("aws-marketplace",)) -> List[Dict[str, str]]:
        response = self.client.describe_images(
            Filters=[
                {'Name': "name", 'Values': ["FreeBSD*"]},
                {'Name': "state", 'Values': ["available"]},
            ],
            Owners=list(owners),
        )
        images = response['Images']
        images.sort(key=lambda x: x['CreationDate'], reverse=True)
        return images

    @functools.cache
    def instance_types(self):
        response = self.client.describe_instance_types()
        instance_types = response['InstanceTypes']
        instance_types.sort(key=lambda x: x['InstanceType'])
        return instance_types


class EC2MetaTask(Task):
    parameters = {
        # XXX-MJ need a mechanism to set a default value for this from the config file
        'aws_region': TaskParameter(
            description="AWS region to use",
            default="us-east-1",
        ),
    }


class EC2LaunchTask(EC2MetaTask):
    """
    Launch an EC2 instance accessible via ssh.
    """
    name = "ec2-launch-freebsd"

    parameters = {
        'image_id': TaskParameter(
            description="AMI ID of the FreeBSD image to launch",
            required=True,
        ),
        'instance_type': TaskParameter(
            description="EC2 instance type to launch",
            required=True,
        ),
        'volume_size': TaskParameter(
            description="Size of the root volume in GiB",
            type=int,
            default=20,
        ),
    }

    def run(self, ctx):
        provider = EC2Provider(self.config, self.aws_region)
        key_name = "bricoler-key"
        keyfile = provider.create_ssh_keypair(
            key_name=key_name,
            tag_value=str(self.config.uuid),
        )
        instance = provider.create_instance(
            image_id=self.image_id,
            instance_type=self.instance_type,
            key_name=key_name,
            volume_size=self.volume_size,
            tag_value=str(self.config.uuid),
        )
        # XXX-MJ still need to ensure that the security group allows ssh access
        info(f"Instance launched: {instance.id}")
        info(f"SSH command: ssh -i {keyfile} ec2-user@{instance.public_dns_name}")
        return {}


class EC2CleanTask(EC2MetaTask):
    """
    Clean up EC2 resources created by bricoler.

    By default it only cleans up resources created in the current workdir; the
    "all" parameter can be used to clean up all resources created by bricoler
    using a given IAM account.
    """
    name = "ec2-clean"

    parameters = {
        'all': TaskParameter(
            description="Clean up all EC2 resources created by bricoler across all workdirs",
            type=bool,
            default=False,
        ),
    }

    def run(self, ctx):
        provider = EC2Provider(self.config, self.aws_region)
        provider.clean(str(self.config.uuid) if not self.all else "*")
        return {}


class EC2ListAMIsTask(EC2MetaTask):
    """
    List FreeBSD AMIs available from the specified owner.
    """
    name = "ec2-list-freebsd-amis"

    parameters = {
        'owners': TaskParameter(
            description="Space-separated list of AMI owners to filter by",
            default="782442783595",  # FreeBSD community AMIs
        ),
    }

    def run(self, ctx):
        provider = EC2Provider(self.config, self.aws_region)
        amis = provider.freebsd_amis(tuple(self.owners.split()))
        json.dump(amis, sys.stdout, indent=2)
        return {}


class EC2ListInstanceTypesTask(EC2MetaTask):
    """
    List all EC2 instance types in a given region.
    """
    name = "ec2-list-instance-types"

    parameters = {
        'min_ncpu': TaskParameter(
            description="Filter instance types by minimum number of CPUs",
            type=int,
            default=1,
        ),
        'min_memory': TaskParameter(
            description="Filter instance types by minimum memory (in MiB)",
            type=int,
            default=256,
        ),
    }

    def run(self, ctx):
        provider = EC2Provider(self.config, self.aws_region)
        instance_types = provider.instance_types()
        for it in instance_types:
            if it['VCpuInfo']['DefaultVCpus'] < self.min_ncpu:
                continue
            if it['MemoryInfo']['SizeInMiB'] < self.min_memory:
                continue
            json.dump(it, sys.stdout, indent=2)
        return {}


#
# Features to add:
# - automatic bisection for build and test failures
# - sending mail upon completion of a task
#   - or, e.g., when syzkaller finds a new report
# - ability to skip dependent tasks
# - tasks to cross-build package repos
# - tasks to boot FreeBSD in different clouds
# - tasks for performance regression testing
# - integration with project infrastructure, e.g., bugzilla, phabricator
#   - src builds could have an option to apply patches from phab/GH first, for instance
#
def main() -> int:
    config = Config()
    try:
        (args, action) = config.load(TaskMeta.lookup)
    except ValueError as e:
        print(f"usage error: {e}")
        return 1

    if not args.task:
        if args.show:
            print("Available tasks:")
            for task_name in TaskMeta.task_names():
                print(f"  {task_name}")
            for alias in config.aliases:
                print(f"  {alias['alias']} (alias for {alias['task']})")
            return 0
        elif args.list:
            for task_name in TaskMeta.task_names():
                print(task_name)
            for alias in config.aliases:
                print(alias['alias'])
            return 0
        else:
            config.usage()
            return 1

    if args.alias:
        config.add_alias(args.alias)
        return 0

    sched = TaskSchedule(config)
    if args.show:
        # XXX-MJ the formatting here is not good and we're omitting some info
        print(f"{sched.target.name}:")
        if sched.target.__class__.__doc__ is not None:
            print(sched.target.__class__.__doc__.strip() + "\n")
        else:
            print("")
        if len(sched.target.parameters) > 0:
            print("Parameters:")
            width = max(len(name) for name in sched.parameters.keys()) + 2
            for name, param in sched.parameters.items():
                print(f"{name+':':<{width}} {param[0].description}")
                print(f"{'':{width+1}}{str(param[1])}")
    elif args.list:
        for task in sched.tasks.values():
            for name in task.__class__.get_parameter_keys():
                print(f"--{task.name}/{name}")
        for name in sched.target.__class__.get_action_names():
            print(f"{name}")
    elif action is not None:
        sched.run_action(action[0], action[1:])
    else:
        sched.run()
    return 0
