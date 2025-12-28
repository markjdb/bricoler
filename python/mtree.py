#
# Copyright (c) 2018 Alex Richardson
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# SPDX-License-Identifier: BSD-2-Clause
#

import collections.abc
import fnmatch
import os
import shlex
import stat
from collections import OrderedDict
from pathlib import Path, PurePath, PurePosixPath
from typing import Dict, Iterator, List, Optional, Union


class MtreePath(PurePosixPath):
    def __str__(self):
        pathstr = super().__str__()
        if pathstr != ".":
            pathstr = "./" + pathstr
        return pathstr


class MtreeEntry:
    def __init__(self, path: MtreePath, attributes: Dict[str, str]):
        self.path = path
        self.attributes = attributes

    def is_dir(self) -> bool:
        return self.attributes.get("type") == "dir"

    def is_file(self) -> bool:
        return self.attributes.get("type") == "file"

    @classmethod
    def parse(cls, line: str, contents_root: Optional[Path] = None) -> "MtreeEntry":
        elements = shlex.split(line)
        tmppath = elements[0]
        # Ensure that the path is normalized:
        if tmppath != ".":
            assert tmppath[:2] == "./"
            tmppath = tmppath[:2] + os.path.normpath(tmppath[2:])
        path = MtreePath(tmppath)
        attr_dict = OrderedDict()  # keep them in insertion order
        for k, v in map(lambda s: s.split(sep="=", maxsplit=1), elements[1:]):
            # convert relative contents=keys to absolute ones
            if contents_root and k == "contents" and not os.path.isabs(v):
                v = str(contents_root / v)
            attr_dict[k] = v
        return MtreeEntry(path, attr_dict)
        # FIXME: use contents=

    @classmethod
    def parse_all_dirs_in_mtree(cls, mtree_file: Path) -> List["MtreeEntry"]:
        with mtree_file.open("r", encoding="utf-8") as f:
            result = []
            for line in f.readlines():
                if " type=dir" in line:
                    result.append(MtreeEntry.parse(line))
            return result

    def __str__(self) -> str:
        def escape(s):
            # mtree uses strsvis(3) (in VIS_CSTYLE format) to encode path names
            # containing non-printable characters.
            # Note: we only handle spaces here since we haven't seen any other
            # special characters being use. If they do exist in practise we can
            # just update this code to handle them too.
            return s.replace(" ", "\\s")

        components = [escape(str(self.path))]
        for k, v in self.attributes.items():
            components.append(k + "=" + shlex.quote(v))
        return " ".join(components)

    def __repr__(self) -> str:
        return "<MTREE entry: " + str(self) + ">"


class MtreeSubtree(collections.abc.MutableMapping):
    def __init__(self) -> None:
        self.entry: Optional[MtreeEntry] = None
        self.children: Dict[str, "MtreeSubtree"] = OrderedDict()

    @staticmethod
    def _split_key(key):
        if isinstance(key, str):
            key = MtreePath(key)
        elif not isinstance(key, MtreePath):
            if isinstance(key, PurePath):
                key = MtreePath(key)
            else:
                raise TypeError
        if not key.parts:
            return None
        return key.parts[0], MtreePath(*key.parts[1:])

    def __getitem__(self, key):
        split = self._split_key(key)
        if split is None:
            if self.entry is None:
                raise KeyError
            return self.entry
        return self.children[split[0]][split[1]]

    def __setitem__(self, key, value):
        split = self._split_key(key)
        if split is None:
            self.entry = value
            return
        if split[0] not in self.children:
            self.children[split[0]] = MtreeSubtree()
        self.children[split[0]][split[1]] = value

    def __delitem__(self, key):
        split = self._split_key(key)
        if split is None:
            if self.entry is None:
                raise KeyError
            self.entry = None
            return
        del self.children[split[0]][split[1]]

    def __iter__(self):
        if self.entry is not None:
            yield MtreePath()
        for k, v in self.children.items():
            for k2 in v:
                yield MtreePath(k, k2)

    def __len__(self):
        ret = int(self.entry is not None)
        for c in self.children.values():
            ret += len(c)
        return ret

    def _glob(self, patfrags: "list[str]", prefix: MtreePath, *, case_sensitive=False) -> Iterator[MtreePath]:
        if len(patfrags) == 0:
            if self.entry is not None:
                yield prefix
            return
        patfrag = patfrags[0]
        patfrags = patfrags[1:]
        if len(patfrags) == 0 and len(patfrag) == 0:
            if self.entry is not None and self.entry.attributes["type"] == "dir":
                yield prefix
            return
        for k, v in self.children.items():
            if fnmatch.fnmatch(k, patfrag):
                # noinspection PyProtectedMember
                yield from v._glob(patfrags, prefix / k, case_sensitive=case_sensitive)

    def glob(self, pattern: str, *, case_sensitive=False) -> Iterator[MtreePath]:
        if len(pattern) == 0:
            return iter([])
        head, tail = os.path.split(pattern)
        patfrags = [tail]
        while head:
            head, tail = os.path.split(head)
            patfrags.insert(0, tail)
        return self._glob(patfrags, MtreePath(), case_sensitive=case_sensitive)

    def _walk(self, top, prefix) -> Iterator[tuple[MtreePath, List[str], List[str]]]:
        split = self._split_key(top)
        if split is not None:
            if split[0] in self.children:
                yield from self.children[split[0]]._walk(split[1], prefix / split[0])
            return
        if self.entry is not None and self.entry.attributes["type"] != "dir":
            return
        files: "list[tuple[str, MtreeSubtree]]" = []
        dirs: "list[tuple[str, MtreeSubtree]]" = []
        for k, v in self.children.items():
            if v.entry is not None and v.entry.attributes["type"] != "dir":
                files.append((k, v))
            else:
                dirs.append((k, v))
        yield prefix, list([k for k, _ in dirs]), list([k for k, _ in files])
        for _, v in dirs:
            yield from v._walk(MtreePath(), prefix)

    def walk(self, top) -> "Iterator[tuple[MtreePath, list[str], list[str]]]":
        return self._walk(top, MtreePath())


class MtreeFile:
    def __init__(self, file: Optional[Path] = None, contents_root: Optional[Path] = None):
        self._mtree = MtreeSubtree()
        if file:
            self.load(file, contents_root=contents_root, append=False)

    def load(self, file: Path, append: bool, contents_root: Optional[Path] = None):
        with file.open("r") as f:
            if not append:
                self._mtree.clear()
            for line in f.readlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                entry = MtreeEntry.parse(line, contents_root)
                key = entry.path
                keystr = str(key)
                assert keystr == "." or os.path.normpath(keystr[2:]) == keystr[2:]
                if key in self._mtree and not entry.is_dir():
                    raise ValueError(f"Duplicate entry for {key} in mtree file")
                self._mtree[key] = entry

    @staticmethod
    def _ensure_mtree_mode_fmt(mode: Union[str, int]) -> str:
        if not isinstance(mode, str):
            mode = "0" + oct(mode)[2:]
        assert mode.startswith("0")
        return mode

    @staticmethod
    def _ensure_mtree_path_fmt(path: str) -> MtreePath:
        # The path in mtree always starts with ./
        assert not path.endswith("/")
        assert path, "PATH WAS EMPTY?"
        mtree_path = path
        if mtree_path != ".":
            # ensure we normalize paths to avoid conflicting duplicates:
            mtree_path = "./" + os.path.normpath(path)
        return MtreePath(mtree_path)

    @staticmethod
    def infer_mode_string(path: Path, should_be_dir) -> str:
        result = f"0{stat.S_IMODE(path.lstat().st_mode):o}"  # format as octal with leading 0 prefix
        # make sure that the .ssh config files are installed with the right permissions
        if path.name == ".ssh" and result != "0700":
            return "0700"
        if path.parent.name == ".ssh" and not path.name.endswith(".pub") and result != "0600":
            return "0600"
        return result

    def add_file(
        self,
        file: Optional[Path],
        path_in_image,
        mode=None,
        uname="root",
        gname="wheel",
        parent_dir_mode=None,
        symlink_dest: Optional[str] = None,
    ):
        if isinstance(path_in_image, PurePath):
            path_in_image = str(path_in_image)
        assert not path_in_image.startswith("/")
        assert not path_in_image.startswith("./") and not path_in_image.startswith("..")
        if mode is None:
            if symlink_dest is not None:
                mode = "0755"
            else:
                assert file is not None
                mode = self.infer_mode_string(file, False)
        mode = self._ensure_mtree_mode_fmt(mode)
        mtree_path = self._ensure_mtree_path_fmt(path_in_image)
        assert str(mtree_path) != ".", "files should not have name ."
        if symlink_dest is not None:
            assert file is None
            reference_dir = None
            mtree_type = "link"
            last_attrib = ("link", str(symlink_dest))
        else:
            assert file is not None
            reference_dir = file.parent
            if file.is_symlink():
                mtree_type = "link"
                last_attrib = ("link", os.readlink(str(file)))
            else:
                mtree_type = "file"
                # now add the actual entry (with contents=/path/to/file)
                contents_path = str(file.absolute())
                last_attrib = ("contents", contents_path)
        self.add_dir(
            str(Path(path_in_image).parent),
            mode=parent_dir_mode,
            uname=uname,
            gname=gname,
            reference_dir=reference_dir,
        )
        attribs = OrderedDict([("type", mtree_type), ("uname", uname), ("gname", gname), ("mode", mode), last_attrib])
        entry = MtreeEntry(mtree_path, attribs)
        self._mtree[mtree_path] = entry

    def add_symlink(self, *, src_symlink: Optional[Path] = None, symlink_dest=None, path_in_image: str, **kwargs):
        if src_symlink is not None:
            assert symlink_dest is None
            self.add_file(src_symlink, path_in_image, **kwargs)
        else:
            assert src_symlink is None
            self.add_file(None, path_in_image, symlink_dest=str(symlink_dest), **kwargs)

    def add_dir(self, path, mode=None, uname="root", gname="wheel", reference_dir=None) -> None:
        if isinstance(path, PurePath):
            path = str(path)
        assert not path.startswith("/")
        path = path.rstrip("/")
        mtree_path = self._ensure_mtree_path_fmt(path)
        if mtree_path in self._mtree:
            return
        if mode is None:
            if reference_dir is None or str(mtree_path) == ".":
                mode = "0755"
            else:
                mode = self.infer_mode_string(reference_dir, True)
        mode = self._ensure_mtree_mode_fmt(mode)
        # Ensure that SSH will work even if the extra-file directory has wrong permissions
        if (path == "root" or path == "root/.ssh") and mode != "0700" and mode != "0755":
            mode = "0755"
        # recursively add all parent dirs that don't exist yet
        parent = str(Path(path).parent)
        if parent != path:  # avoid recursion for path == "."
            if reference_dir is not None:
                self.add_dir(parent, None, uname, gname, reference_dir=reference_dir.parent)
            else:
                self.add_dir(parent, mode, uname, gname, reference_dir=None)
        # now add the actual entry
        attribs = OrderedDict([("type", "dir"), ("uname", uname), ("gname", gname), ("mode", mode)])
        entry = MtreeEntry(mtree_path, attribs)
        self._mtree[mtree_path] = entry

    def add_from_mtree(self, mtree_file: "MtreeFile", path: Union[PurePath, str]):
        if isinstance(path, PurePath):
            path = str(path)
        assert not path.startswith("/")
        path = path.rstrip("/")
        mtree_path = self._ensure_mtree_path_fmt(path)
        if self.get(mtree_path) is not None:
            return
        subtree = mtree_file.get(mtree_path)
        if subtree is None:
            raise ValueError(f"Could not find {mtree_path} in source mtree")
        parent = mtree_path.parent
        if parent != mtree_path:
            self.add_from_mtree(mtree_file, parent)
        attribs = subtree.attributes
        entry = MtreeEntry(mtree_path, attribs)
        self._mtree[mtree_path] = entry

    def __contains__(self, item) -> bool:
        mtree_path = self._ensure_mtree_path_fmt(str(item))
        return mtree_path in self._mtree

    def exclude_matching(self, globs, exceptions=None) -> None:
        """Remove paths matching any pattern in globs (but not matching any in exceptions)"""
        if exceptions is None:
            exceptions = []
        if isinstance(globs, str):
            globs = [globs]
        for glob in globs + exceptions:
            # glob must be anchored at the root (./) or start with a pattern
            assert glob[:2] == "./" or glob[:1] == "?" or glob[:1] == "*"
        paths_to_remove = set()
        for path, entry in self._mtree.items():
            for glob in globs:
                if fnmatch.fnmatch(path, glob):
                    delete = True
                    for exception in exceptions:
                        if fnmatch.fnmatch(path, exception):
                            delete = False
                            break
                    if delete:
                        paths_to_remove.add(path)
        for path in paths_to_remove:
            self._mtree.pop(path)

    def __repr__(self) -> str:
        import pprint

        return "<MTREE: " + pprint.pformat(self._mtree) + ">"

    def write(self, output: Path):
        with output.open("w", encoding="utf-8") as f:
            f.write("#mtree 2.0\n")
            for path in sorted(self._mtree.keys()):
                f.write(str(self._mtree[path]) + "\n")

    def get(self, key) -> Optional[MtreeEntry]:
        return self._mtree.get(key)

    @property
    def root(self) -> MtreeSubtree:
        return self._mtree

    def glob(self, pattern: str, *, case_sensitive=False) -> Iterator[MtreePath]:
        return self._mtree.glob(pattern, case_sensitive=case_sensitive)

    def walk(self, top) -> Iterator[tuple[MtreePath, list[str], list[str]]]:
        return self._mtree.walk(top)
