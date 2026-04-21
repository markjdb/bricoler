#
# Copyright (c) Mark Johnston <markj@FreeBSD.org>
#
# SPDX-License-Identifier: BSD-2-Clause
#

import functools
import glob
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
from .vm import FreeBSDVM, VMImage, VMHypervisor, BhyveRun, QEMURun, RVVMRun, SSHCommandRunner


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
        'branch': TaskParameter(
            description="Branch to check out",
        ),
        'shallow': TaskParameter(
            description="Perform a shallow clone and fetch",
            default=True,
        ),
        'url': TaskParameter(
            description="URL of the Git repository to clone, or a filesystem path",
            required=True,
        ),
    }
    outputs = {
        'repo': GitRepository
    }

    def run(self, ctx, repotype: Type[GitRepository] = GitRepository):
        repo = repotype(self.url, Path("./src"), self.branch,
                        shallow=self.shallow, no_cmds=self.skip)
        repo.update(shallow=self.shallow)
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
        'repo': FreeBSDSrcRepository,
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

        # If the kernel config is a path, extract the basename and dirname.
        kernconf = self.kernel_config
        kernconfdir = None
        if '/' in kernconf:
            kernconf = Path(kernconf).name
            kernconfdir = Path(self.kernel_config).parent

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
                f"KERNCONF={kernconf}",
            ]
            if kernconfdir is not None:
                args.append(f"KERNCONFDIR={kernconfdir}")
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
            'repo': self.src.repo,
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
        'single_user': TaskParameter(
            description="Boot into single-user mode",
            default=False,
        ),
        'sudo_users': TaskParameter(
            description="A list of users to grant sudo privileges, useful for tests",
            type=str,
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
                        """
                        none /dev/fd fdescfs rw 0 0
                        /dev/gpt/swap non swap sw 0 0
                        """)

        add_config_file("boot/loader.conf",
                        "autoboot_delay=1",
                        "beastie_disable=YES",
                        "loader_logo=none",
                        "console=comconsole",
                        "kernel_options=-s" if self.single_user else "",
                        "kern.geom.label.disk_ident.enable=0",
                        "p9fs_load=YES",
                        "virtio_p9fs_load=YES",
                        "zfs_load=YES" if self.filesystem == FreeBSDVMImageFilesystem.ZFS else "",
                        *[tunable for tunable in self.loader_tunables.split()])

        if self.sysctls is not None:
            add_config_file("etc/sysctl.conf",
                            *[sysctl for sysctl in self.sysctls.split()],
                            source=(stagedir / "etc/sysctl.conf"))

        if self.sudo_users is not None:
            for user in self.sudo_users.split():
                add_config_file(f"usr/local/etc/sudoers.d/{user}",
                                f"{user} ALL=(ALL) NOPASSWD: ALL")

        add_config_file("firstboot")

        if self.packages is not None and len(self.packages) > 0:
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
            pkg_cmd("-o", f"PKG_CACHEDIR={pkg_dir}", "clean")
            pkg_cmd("repo", pkg_dir)

            pkg_version = pkg_cmd("rquery", "%v", "pkg", capture_output=True).stdout
            pkg_version = pkg_version.decode().strip()
            pkg_pkg = "pkg-" + pkg_version + ".pkg"

            # We might have fetched a hashed package.  Make a symlink so the script
            # can find it during boot.  pkg-fetch sports a --symlink option that's
            # supposed to do it, but it creates broken symlinks at the moment. See
            # https://github.com/freebsd/pkg/pull/2587
            if not Path(pkg_dir / "All" / pkg_pkg).is_file():
                matches = glob.glob(str(pkg_dir / "All/Hashed" / f"pkg-{pkg_version}*.pkg"))
                if len(matches) > 0:
                    (pkg_dir / "All" / pkg_pkg).symlink_to(Path("Hashed") / Path(matches[0]).name)
                else:
                    raise ValueError(f"Could not find fetched {pkg_pkg} in {pkg_dir / 'All'}")

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
                                IGNORE_OSVERSION=yes pkg add -r local {pkg_pkg}
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
        'disk_list': TaskParameter(
            description="A list of extra files to add as disks",
            type=str
        ),
        'hypervisor': TaskParameter(
            description="Hypervisor to use for running the VM",
            type=VMHypervisor,
            # XXX-MJ should somehow default to qemu for non-native images
            default=lambda: VMHypervisor.BHYVE if BhyveRun.canrun() else VMHypervisor.QEMU,
        ),
        'interactive': TaskParameter(
            description="Run the VM in interactive mode",
            default=True,
        ),
        'memory': TaskParameter(
            description="Amount of memory to allocate to the VM in MiB",
            default=2048,
        ),
        'ncpus': TaskParameter(
            description="Number of CPUs to allocate to the VM",
            default=2,
        ),
        'p9_shares': TaskParameter(
            description="Comma-separated list of shares of the form <share>:<path>",
            type=str,  # XXX-MJ List[Tuple[str, Path]]
        ),
        'reboot': TaskParameter(
            description="Restart the VM when it exits due to a reboot",
            default=False,
        ),
    }

    outputs = {
        'vm': Optional[FreeBSDVM],
    }

    def run(self, ctx):
        match self.hypervisor:
            case VMHypervisor.BHYVE: cls = BhyveRun
            case VMHypervisor.QEMU: cls = QEMURun
            case VMHypervisor.RVVM: cls = RVVMRun
        if self.p9_shares:
            p9_shares = [tuple(desc.split(':')) for desc in self.p9_shares.split(',')]
        else:
            p9_shares = []
        vmrun = cls(
            image=self.vm_image.image,
            extra_disks=self.disk_list.split() if self.disk_list else [],
            memory=self.memory,
            ncpus=self.ncpus,
            p9_shares=p9_shares,
            ssh_key=self.vm_image.ssh_key,
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

        if self.interactive:
            self.run_cmd(vmrun.setup())
            vm = None
        else:
            console_log = open("vm-console.log", "wb")
            vm = FreeBSDVM(vmrun, logfiles=[console_log, sys.stdout.buffer])

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
        gdb_cmd += args
        self.run_cmd(gdb_cmd)

    def _ssh(self, *args):
        with open(Path.cwd() / "ssh-addr", "r") as f:
            addr = f.read().strip()
        (host, portstr) = addr.split(':', maxsplit=1)
        ssh = SSHCommandRunner((host, portstr), Path.cwd() / "ssh_key")
        ssh.run_cmd()

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
        "pimd",
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
        "if_bridge", "if_enc", "if_epair", "if_geneve", "if_ovpn", "if_stf", "if_wg",
        "ipdivert",
        "ipfw", "ipfw_nat", "ipfw_nptv6",
        "ip_mroute", "ip6_mroute",
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
            default=1,
        ),
        'parallelism': TaskParameter(
            description="Number of tests to run in parallel",
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
                "-o", "/root/kyua-report.txt",
                self.tests
            ]
            vm.sendline(" ".join(cmd))
            vm.wait_for_prompt(timeout=10*3600)

            ssh = SSHCommandRunner(vm.vmrun.ssh_addr, vm.vmrun.ssh_key)
            ssh.scp_from("/root/kyua.db", Path.cwd() / "kyua.db")
            ssh.scp_from("/root/kyua-report.txt", Path.cwd() / "kyua-report.txt")
        except FreeBSDVM.PanicException as e:
            self._gdb("-ex", f"thread {e.cpuid + 1}")
            raise e
        return outputs

    def _report(self, *args):
        self.run_cmd(["less", Path.cwd() / "kyua-report.txt"])

    actions = {
        'report': _report,
    }


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
            default=1,
        ),
        'min_memory': TaskParameter(
            description="Filter instance types by minimum memory (in MiB)",
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


class OpenZFSGitCheckoutTask(GitCheckoutTask):
    """
    Clone the OpenZFS repository, or update an existing clone.
    """
    name = "openzfs-git-checkout"

    url = "https://github.com/openzfs/zfs"
    branch = "master"

    outputs = {
        'repo': GitRepository,
    }


class OpenZFSBuildTask(Task):
    """
    Build OpenZFS from a Git repository checkout.
    """
    name = "openzfs-build"

    parameters = {
        'clean': TaskParameter(
            description="Clean build artifacts before building",
            default=False
        ),
        'sysdir': TaskParameter(
            description="Path to the FreeBSD kernel source to compile against",
            default=Path("/usr/src/sys")
        ),
    }

    inputs = {
        'src': OpenZFSGitCheckoutTask,
    }

    outputs = {
        'user_stagedir': Path,
        'kmod_stagedir': Path,
    }

    def run(self, ctx):
        user_stagedir = Path("./install-user").resolve()
        user_stagedir.mkdir(parents=True, exist_ok=True)
        kmod_stagedir = Path("./install-kmod").resolve()
        kmod_stagedir.mkdir(parents=True, exist_ok=True)

        # Build and stage userspace components first.
        with chdir(self.src.repo.path):
            if not Path("./configure").is_file() or self.clean:
                self.run_cmd(["./autogen.sh"])
            if not Path("./Makefile").is_file() or self.clean:
                self.run_cmd([
                    "./configure",
                    "MAKE=gmake",
                    "--with-config=user",
                    "--enable-invariants",
                    "--enable-debug",
                ])
            self.run_cmd(["gmake", "-j", str(ctx.max_jobs)])
            self.run_cmd(["gmake", "install", f"DESTDIR={user_stagedir}"])

        # Now build the kernel module.
        with chdir(self.src.repo.path / "module"):
            if self.clean:
                self.run_cmd(["make", "-f", "Makefile.bsd", "clean"])
            self.run_cmd([
                "make", "-s",
                "-j", str(ctx.max_jobs),
                "-f", "Makefile.bsd",
                "CC=cc",
                f"SYSDIR={self.sysdir}",
                "WITH_DEBUG=true"
            ])
            self.run_cmd([
                "make", "-s",
                "-f", "Makefile.bsd",
                "install",
                f"KMODOWN={os.geteuid()}",
                f"KMODGRP={os.getegid()}",
                "KMODDIR=",
                "DEBUGDIR=",
                f"DESTDIR={kmod_stagedir}",
                "WITHOUT_DEBUG_FILES=",
            ])

        return {
            'user_stagedir': user_stagedir,
            'kmod_stagedir': kmod_stagedir,
        }


class OpenZFSTestSuiteFreeBSDSrcBuildTask(FreeBSDSrcBuildAndInstallTask):
    make_options = " ".join([
        "WITHOUT_LIB32=",
        "WITHOUT_TOOLCHAIN=",
        "WITHOUT_ZFS=",
    ])


class OpenZFSTestSuiteBuildTask(OpenZFSBuildTask):
    inputs = {
        'freebsd_build': OpenZFSTestSuiteFreeBSDSrcBuildTask,
    }

    outputs = OpenZFSBuildTask.outputs | OpenZFSTestSuiteFreeBSDSrcBuildTask.outputs

    def run(self, ctx):
        # XXX-MJ also needs to ensure that userspace is built against a sysroot
        # instead of the host.
        self.sysdir = self.freebsd_build.repo.path / "sys"
        return super().run(ctx) | self.freebsd_build.__dict__


class OpenZFSTestSuiteVMImageTask(FreeBSDVMImageTask):
    filesystem = FreeBSDVMImageFilesystem.UFS

    image_size = 50

    packages = " ".join([
        "bash",
        "devel/py-sysctl",
        "fio",
        "jq",
        "ksh93",
        "libunwind",
        "pamtester",
        "python3",
        "rsync",
        "sudo",
        "xxhash",
    ])

    sudo_users = "tests"

    inputs = {
        'build': OpenZFSTestSuiteBuildTask,
    }

    def run(self, ctx):
        mtree = self.build.metalog

        kmoddir = self.build.kmod_stagedir
        mtree.add_file(kmoddir / "openzfs.ko",
                       Path("boot/kernel/openzfs.ko"))
        mtree.add_file(kmoddir / "openzfs.ko.debug",
                       Path("usr/lib/debug/boot/kernel/openzfs.ko"))

        def add_overlay(root: Path) -> None:
            if not root.is_dir():
                raise ValueError(f"Overlay path '{root}' is not a directory")
            for item in root.rglob('*'):
                rel = item.relative_to(root)
                if item.is_dir():
                    mtree.add_dir(rel)
                elif item.is_file():
                    mtree.add_file(item, rel)
                elif item.is_symlink():
                    mtree.add_symlink(src_symlink=item, path_in_image=rel)
                else:
                    raise ValueError(
                        f"Unsupported file type for overlay: {item}"
                    )

        add_overlay(self.build.user_stagedir)

        return super().run(ctx)


class OpenZFSTestSuiteTask(FreeBSDVMBootTask):
    """
    Boot a virtual machine and run the OpenZFS test suite (ZTS).
    """
    name = "openzfs-test-suite"

    interactive = False
    ncpus = os.cpu_count() // 2
    memory = 1024 * (os.cpu_count() // 2)

    inputs = {
        'vm_image': OpenZFSTestSuiteVMImageTask,
    }

    def run(self, ctx):
        disk_list = ""
        for disk in range(3):
            with open(f"disk{disk}", "wb") as f:
                f.truncate(50 * 1024 * 1024 * 1024)
            disk_list += f" disk{disk}"
        self.disk_list = disk_list

        outputs = super().run(ctx)
        vm: FreeBSDVM = outputs['vm']
        if vm is None:
            raise ValueError(
                "Cannot run tests, VM must be run in non-interactive mode"
            )

        try:
            vm.boot_to_login()
            cmd = "/usr/local/share/zfs/zfs-tests.sh -v"
            vm.sendline(f"DISKS=\"vtbd1 vtbd2 vtbd3\" su -m tests -c \"{cmd}\"")
            vm.wait_for_prompt(timeout=10*3600)

            ssh = SSHCommandRunner(vm.vmrun.ssh_addr, vm.vmrun.ssh_key)
            ssh.scp_from("/var/tmp/test_results/current", Path.cwd() / "test_results")
        except FreeBSDVM.PanicException as e:
            self._gdb("-ex", f"thread {e.cpuid + 1}")
            raise e
        return outputs


class SyzkallerGitCheckoutTask(GitCheckoutTask):
    """
    Clone the syzkaller repository, or update an existing clone.
    """
    name = "syzkaller-git-checkout"

    url = "https://github.com/google/syzkaller"
    branch = "master"
    shallow = False  # Some syzkaller tests require a full clone.

    outputs = {
        'repo': GitRepository,
    }


class SyzkallerBuildTask(Task):
    """
    Build syzkaller from a Git repository checkout.
    """
    name = "syzkaller-build"

    parameters = {
        'test': TaskParameter(
            description="Run tests after building",
            default=True
        ),
    }

    inputs = {
        'src': SyzkallerGitCheckoutTask,
    }

    outputs = {
        'bindir': Path,
        'repo': GitRepository,
    }

    def run(self, ctx):
        with chdir(self.src.repo.path):
            env = {'GOMAXPROCS': str(ctx.max_jobs)}
            self.run_cmd(["gmake"], env=env)
            if self.test:
                self.run_cmd(["gmake", "test"], env=env)
        return {
            'bindir': self.src.repo.path / "bin",
            'repo': self.src.repo,
        }


class SyzkallerFuzzFreeBSDBuildTask(FreeBSDSrcBuildAndInstallTask):
    def run(self, ctx):
        with open("SYZKALLER", "w") as f:
            f.write("# Added by bricoler\n"
                   f"include {self.kernel_config}\n"
                    "ident SYZKALLER\n"
                    "options COVERAGE\n"
                    "options KCOV\n")
            f.flush()
            self.kernel_config = str(Path.cwd() / "SYZKALLER")
            return super().run(ctx)


class SyzkallerFuzzFreeBSDVMImageTask(FreeBSDVMImageTask):
    inputs = {
        'build': SyzkallerFuzzFreeBSDBuildTask,
    }


class SyzkallerFuzzFreeBSDTask(Task):
    """
    Run syzkaller against a FreeBSD target
    """
    name = "syzkaller-fuzz-freebsd"

    parameters = {
        'dashboard_addr': TaskParameter(
            description="Address of the syzkaller HTTP dashboard",
            default="0.0.0.0:8080",
        ),
        'debug': TaskParameter(
            description="Run syzkaller in debug mode with a single VM and verbose logging",
            default=False,
        ),
        'hypervisor': TaskParameter(
            description="Hypervisor to use for running the VM",
            type=VMHypervisor,
            default=VMHypervisor.BHYVE if BhyveRun.canrun() else VMHypervisor.QEMU,
        ),
        'vm_count': TaskParameter(
            description="Number of VMs to run in parallel (ignored in debug mode)",
            default=os.cpu_count() // 2,
        ),
        'vm_ncpu': TaskParameter(
            description="Number of CPUs to allocate to each VM",
            default=2,
        ),
        'vm_memory': TaskParameter(
            description="Amount of memory to allocate to each VM in MiB",
            default=2048,
        ),
        'zfs_dataset': TaskParameter(
            description="ZFS dataset to use for storing syzkaller workdir and VM images",
            type=str,
        )
    }

    inputs = {
        'syzkaller': SyzkallerBuildTask,
        'vm_image': SyzkallerFuzzFreeBSDVMImageTask,
    }

    def run(self, ctx):
        hypervisor_args = {}
        image_path = None
        if self.hypervisor == VMHypervisor.BHYVE:
            if self.zfs_dataset is None:
                raise ValueError("zfs_dataset parameter is required when using bhyve")
            def zfs_get(dataset, prop):
                cmd = ["zfs", "get", "-H", "-o", "value", prop, dataset]
                return self.run_cmd(cmd, capture_output=True).stdout.decode().strip()
            mountpoint = zfs_get(self.zfs_dataset, "mountpoint")
            if mountpoint == "none":
                raise ValueError(f"ZFS dataset {self.zfs_dataset} is not mounted")

            # bhyve doesn't support transient disk snapshots, so we have to provide
            # a ZFS dataset to syz-manager that it can clone.
            hypervisor_args['dataset'] = self.zfs_dataset
            hypervisor_args['bootrom'] = "/usr/local/share/uefi-firmware/BHYVE_UEFI.fd"

            image_path = str(Path(mountpoint) / "syzkaller.img")
            shutil.copyfile(self.vm_image.image.path, image_path)
        else:
            # --enable-kvm is hard-coded in the QEMU parameters for FreeBSD
            # targets, so we have to do this fragile thing to remove it.
            hypervisor_args['qemu_args'] = ""

            image_path = self.vm_image.image.path

        workdir = Path.cwd() / "workdir"
        workdir.mkdir(exist_ok=True)

        machine = self.vm_image.image.machine.split('/', maxsplit=1)[1]
        params = {
            'target': f"freebsd/{machine}",
            'workdir': str(workdir),
            'type': f"{self.hypervisor.value.lower()}",
            'syzkaller': str(self.syzkaller.repo.path),
            'image': str(image_path),
            'http': self.dashboard_addr,
            'ssh_user': "root",
            'sshkey': str(self.vm_image.ssh_key),
            'procs': 2,
            'vm': {
                'cpu': self.vm_ncpu,
                'mem': str(self.vm_memory) + "M",
                'count': self.vm_count,
            } | hypervisor_args,
        }

        # Write the parameters to a JSON config file.
        with open("syz-manager.cfg", "w") as f:
            json.dump(params, f, indent=2)

        cmd = [self.syzkaller.bindir / "syz-manager", "-config", "syz-manager.cfg"]
        if self.debug:
            cmd.append("-debug")
        self.run_cmd(cmd)

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
