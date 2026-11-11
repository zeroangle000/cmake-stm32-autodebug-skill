#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolresolve —— 跨平台工具发现 + 版本门禁（可被 env_doctor / flash_loop import）

设计原则（为什么不能写死路径）：
  这个 skill 要给别人用，别人的 gcc 可能在 winget 目录、可能在 C:\\xpack*、
  也可能在 /opt 或 Homebrew。所以只要求"能找到一个能跑的"，不要求位置一致。

发现顺序（优先级从高到低）：
  1. 显式 config（config/project.json 的 paths.<tool>）
  2. 环境变量（CMSK_GCC / CMSK_OPENOCD / ...）
  3. PATH（shutil.which）
  4. 常见安装位置（按平台枚举，见 SEARCH_GLOBS）
  5. 都没有 -> 返回 None，由调用方给出安装指引

版本门禁不达标时不算"找到"，但会把找到的路径和版本一起报出来，方便判断。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys

IS_WIN = (os.name == "nt")
EXE = ".exe" if IS_WIN else ""

# ---------------------------------------------------------------- 工具规格
# bins    : PATH 里可能出现的可执行名
# env     : 覆盖用环境变量
# cfg     : config/project.json 里 paths.<cfg>
# need    : True = 缺了不能干活（exit 6）；False = 只有对应功能需要
# minv    : 最低版本（主, 次）
SPECS = {
    "gcc": {
        "bins": ["arm-none-eabi-gcc"], "env": "CMSK_GCC", "cfg": "gcc",
        "ver": ["-dumpversion"], "need": True, "minv": (10, 3),
        "label": "ARM GCC (arm-none-eabi-gcc)",
    },
    "gdb": {
        "bins": ["arm-none-eabi-gdb"], "env": "CMSK_GDB", "cfg": "gdb",
        "ver": ["--version"], "need": False, "minv": (10, 0),
        "label": "arm-none-eabi-gdb",
    },
    "cmake": {
        "bins": ["cmake"], "env": "CMSK_CMAKE", "cfg": "cmake",
        "ver": ["--version"], "need": True, "minv": (3, 20),
        "label": "CMake",
    },
    "ninja": {
        "bins": ["ninja"], "env": "CMSK_NINJA", "cfg": "ninja",
        "ver": ["--version"], "need": False, "minv": (1, 10),
        "label": "Ninja",
    },
    "python": {
        "bins": ["python", "python3"], "env": "CMSK_PYTHON", "cfg": "python",
        "ver": ["-V"], "need": True, "minv": (3, 8),
        "label": "Python",
    },
    "pyocd": {
        "bins": ["pyocd"], "env": "CMSK_PYOCD", "cfg": "pyocd",
        "ver": ["--version"], "need": False, "minv": (0, 34),
        "label": "pyOCD",
    },
    "openocd": {
        "bins": ["openocd"], "env": "CMSK_OPENOCD", "cfg": "openocd",
        "ver": ["--version"], "need": False, "minv": (0, 11),
        "label": "OpenOCD",
    },
    # ---- 可选软件：缺了不影响闭环，但 IDE/图形化流程会用到，缺了要提示 ----
    "cubemx": {
        "bins": ["STM32CubeMX"], "env": "CMSK_CUBEMX", "cfg": "cubemx",
        "ver": ["-v"], "need": False, "minv": (0, 0), "optional": True,
        "label": "STM32CubeMX（生成/改 .ioc 用）",
    },
    "cubeprog": {
        "bins": ["STM32_Programmer_CLI"], "env": "CMSK_CUBEPROG", "cfg": "cubeprog",
        "ver": ["--version"], "need": False, "minv": (0, 0), "optional": True,
        "label": "STM32CubeProgrammer CLI（烧录备选，对低电压更宽容）",
    },
    "clion": {
        "bins": ["clion64", "clion"], "env": "CMSK_CLION", "cfg": "clion",
        "ver": [], "need": False, "minv": (0, 0), "optional": True,
        "label": "CLion（可选 IDE）",
    },
    "vscode": {
        "bins": ["code"], "env": "CMSK_VSCODE", "cfg": "vscode",
        "ver": ["--version"], "need": False, "minv": (0, 0), "optional": True,
        "label": "VS Code（可选 IDE）",
    },
}

# ------------------------------------------------------- 常见安装位置（glob）
_WIN_GLOBS = [
    # xpack / winget 包（openocd、arm-none-eabi-gcc 都可能落这里）
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*\**\bin",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links",
    r"%LOCALAPPDATA%\Programs\*\**\bin",
    # xpack 官方安装位置
    r"%USERPROFILE%\.xpack\**\bin",
    r"C:\xpack*\**\bin",
    # ARM 官方安装器
    r"C:\Program Files\Arm GNU Toolchain arm-none-eabi\**\bin",
    r"C:\Program Files (x86)\Arm GNU Toolchain arm-none-eabi\**\bin",
    r"C:\Program Files\Arm\GNU Toolchain\**\bin",
    # 常见自定义工具链根目录（用户自己的 D:/toolchains 之类）
    r"D:\toolchains\**\bin",
    r"C:\toolchains\**\bin",
    r"%USERPROFILE%\toolchains\**\bin",
]
_WIN_GLOBS += [
    # STM32CubeMX
    r"D:\CubeMx\STM32CubeMX.exe",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeMX\STM32CubeMX.exe",
    r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeMX\STM32CubeMX.exe",
    # STM32CubeProgrammer CLI（ST 的 bundle 目录带版本号）
    r"%LOCALAPPDATA%\stm32cube\bundles\programmer\*\bin",
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin",
    # CLion
    r"C:\Program Files\JetBrains\CLion*\bin",
    r"%LOCALAPPDATA%\JetBrains\Toolbox\apps\CLion\*\*\bin",
    # VS Code
    r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin",
    r"C:\Program Files\Microsoft VS Code\bin",
]

_NIX_GLOBS = [
    "/opt/**/bin", "/usr/local/**/bin", "/usr/bin", "/usr/local/bin",
    os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.xpack/**/bin"),
    "/opt/homebrew/bin", "/usr/local/opt/**/bin",
]


def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))


def _glob_candidates(patterns):
    out = []
    for pat in patterns:
        for hit in glob.glob(_expand(pat), recursive=True):
            if os.path.isdir(hit):
                out.append(hit)
    return out


def _search_dirs():
    pats = _WIN_GLOBS if IS_WIN else _NIX_GLOBS
    seen, dirs = set(), []
    for d in _glob_candidates(pats):
        d = os.path.normcase(os.path.abspath(d))
        if d not in seen:
            seen.add(d)
            dirs.append(d)
    return dirs


def _looks_like(bins, path):
    base = os.path.basename(path).lower()
    for b in bins:
        if base == (b + EXE).lower() or base == b.lower():
            return True
    return False


def find_tool(name, cfg=None, search_dirs=None):
    """按 4 级顺序找一个可执行文件；找不到返回 None"""
    spec = SPECS[name]
    cfg = cfg or {}

    # 1) config
    p = (cfg.get("paths") or {}).get(spec["cfg"])
    if p:
        p = _expand(p)
        if not os.path.isabs(p):
            p = os.path.join(cfg.get("_root", "."), p)
        if os.path.isfile(p):
            return os.path.abspath(p)

    # 2) 环境变量
    envp = os.environ.get(spec["env"])
    if envp:
        envp = _expand(envp)
        if os.path.isfile(envp):
            return os.path.abspath(envp)

    # 3) PATH
    for b in spec["bins"]:
        w = shutil.which(b)
        if w:
            return os.path.abspath(w)

    # 4) 常见目录
    dirs = search_dirs if search_dirs is not None else _search_dirs()
    for d in dirs:
        try:
            for fn in os.listdir(d):
                full = os.path.join(d, fn)
                if os.path.isfile(full) and _looks_like(spec["bins"], full):
                    return os.path.abspath(full)
        except OSError:
            continue
    return None


_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(text):
    m = _VER_RE.search(text or "")
    if not m:
        return None, ""
    parts = [int(m.group(1)), int(m.group(2))]
    if m.group(3) is not None:
        parts.append(int(m.group(3)))
    return tuple(parts), m.group(0)


def version_of(path, name):
    spec = SPECS[name]
    try:
        r = subprocess.run([path] + spec["ver"], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=15)
        txt = r.stdout.decode("utf-8", "replace")
    except Exception as e:                      # noqa: BLE001
        return None, "", "执行失败: %s" % e
    if name == "gcc":
        txt = txt.strip().splitlines()[0] if txt.strip() else ""
    v, raw = parse_version(txt)
    return v, raw, ""


def _ver_ok(v, minv):
    if v is None:
        return False
    a = tuple(v) + (0,) * (len(minv) - len(v))
    return a[:len(minv)] >= tuple(minv)


def scan(cfg=None):
    """返回每个工具的状态；cfg 可含 paths/_root"""
    cfg = cfg or {}
    dirs = _search_dirs()
    rows = []
    for name, spec in SPECS.items():
        path = find_tool(name, cfg, dirs)
        row = {
            "tool": name, "label": spec["label"], "need": spec["need"],
            "min": "%d.%d" % spec["minv"], "path": path,
            "version": None, "version_raw": "", "ok": False, "reason": "",
        }
        row["optional"] = bool(spec.get("optional"))
        if not path:
            row["reason"] = "未找到"
        elif not spec["ver"]:
            row["ok"] = True          # 没有 --version 的 GUI 程序：存在即算找到
        else:
            v, raw, err = version_of(path, name)
            row["version"], row["version_raw"] = v, raw
            if err:
                row["reason"] = err
            elif not _ver_ok(v, spec["minv"]):
                row["reason"] = "版本过低（需要 >= %s）" % row["min"]
            else:
                row["ok"] = True
        rows.append(row)
    return rows


def find_openocd_scripts(openocd_path, cfg=None):
    """openocd 的 scripts 目录可能在包根下 openocd/scripts，也可能 share/openocd/scripts"""
    if not openocd_path:
        return None
    cands = []
    p = (cfg or {}).get("paths") or {}
    if p.get("openocd_scripts"):
        cands.append(_expand(p["openocd_scripts"]))
    root = os.path.dirname(os.path.dirname(openocd_path))     # .../bin/openocd -> 包根
    cands += [
        os.path.join(root, "openocd", "scripts"),
        os.path.join(root, "share", "openocd", "scripts"),
        os.path.join(root, "scripts"),
        "/usr/share/openocd/scripts",
        "/usr/local/share/openocd/scripts",
        "/opt/homebrew/share/openocd/scripts",
    ]
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "target")):
            return os.path.abspath(c)
    return None


def load_project_config(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_root"] = os.path.dirname(os.path.abspath(path))
    return cfg


if __name__ == "__main__":
    as_json = "--json" in sys.argv
    rows = scan()
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            mark = "OK  " if r["ok"] else ("MISS" if not r["path"] else "BAD ")
            print("[%s] %-28s %-12s %s" % (mark, r["label"],
                                           r["version_raw"] or "-", r["path"] or r["reason"]))
