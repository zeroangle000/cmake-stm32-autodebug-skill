#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_doctor —— cmake-stm32-autodebug-skill 的环境体检

检查 6 类：
  1) 工具链：gcc/gdb/cmake/ninja/python/pyocd/openocd（存在 + 版本门禁）
  2) OpenOCD scripts 目录（interface/target 配置文件是否在）
  3) 调试探针（ST-Link 等）是否枚举
  4) 串口：列表 + 目标串口是否被占用
  5) 残留进程（pyocd/openocd 占着探针）
  6) 工程：CMakePresets、构建产物、产物是否比源码新
  （可选 --probe-net：实测各下载源连通性）

用法：
  python scripts/env_doctor.py                 人读
  python scripts/env_doctor.py --json          机器读（AI 用）
  python scripts/env_doctor.py --install-hints 只打印缺项的安装命令
  python scripts/env_doctor.py --probe-net     额外测网络源
  python scripts/env_doctor.py --fix --yes     结束残留 pyocd/openocd 进程（必须带 --yes）

退出码：0 = 必需项齐全；6 = 缺必需项/探针不可用（对应 skill 的 CONFIG 类错误）
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    import toolresolve as TR
except Exception as e:                                   # noqa: BLE001
    print("[FATAL] 无法 import toolresolve.py: %s" % e)
    sys.exit(6)

IS_WIN = (os.name == "nt")

# ---------------------------------------------------------------- 安装指引
# verified: True = 本机实测可用；"partial" = 镜像存在但内容不全；False = 未验证
INSTALL_HINTS = {
    "gcc": [
        {"source": "winget (xpack)", "verified": False,
         "cmd": 'winget install -e --id xpack-dev-tools.arm-none-eabi-gcc'},
        {"source": "ARM 官方", "verified": True,
         "url": "https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads"},
        {"source": "MSYS2 pacman", "verified": "partial",
         "cmd": 'pacman -S mingw-w64-x86_64-arm-none-eabi-gcc',
         "note": "镜像根 https://mirrors.tuna.tsinghua.edu.cn/msys2/ 可用，但具体包名请现场确认"},
    ],
    "gdb": [{"source": "随 ARM GCC 工具链附带", "verified": True, "note": "装 gcc 即可，无需单独装"}],
    "cmake": [
        {"source": "pip 清华源", "verified": True,
         "cmd": 'python -m pip install cmake -i https://pypi.tuna.tsinghua.edu.cn/simple'},
        {"source": "pip 阿里源", "verified": True,
         "cmd": 'python -m pip install cmake -i https://mirrors.aliyun.com/pypi/simple/'},
    ],
    "ninja": [
        {"source": "pip 清华源", "verified": True,
         "cmd": 'python -m pip install ninja -i https://pypi.tuna.tsinghua.edu.cn/simple'},
    ],
    "python": [
        {"source": "官网", "verified": True, "url": "https://www.python.org/downloads/"},
        {"source": "微软商店", "verified": False, "cmd": 'winget install -e --id Python.Python.3.12'},
    ],
    "pyocd": [
        {"source": "pip 清华源", "verified": True,
         "cmd": 'python -m pip install pyocd pyserial -i https://pypi.tuna.tsinghua.edu.cn/simple'},
        {"source": "pip 阿里源", "verified": True,
         "cmd": 'python -m pip install pyocd pyserial -i https://mirrors.aliyun.com/pypi/simple/'},
    ],
    "cubemx": [
        {"source": "ST 官网（需 ST 账号）", "verified": True,
         "url": "https://www.st.com/en/development-tools/stm32cubemx.html",
         "note": "改 .ioc / 重新生成 Core+Drivers 时必需；纯命令行编译可以不装"},
    ],
    "cubeprog": [
        {"source": "ST 官网（需 ST 账号）", "verified": True,
         "url": "https://www.st.com/en/development-tools/stm32cubeprog.html",
         "note": "openocd 因 VTREF 偏低连不上时的备选烧录器（它不做电压门槛检查）"},
    ],
    "clion": [
        {"source": "JetBrains 官网（学生可申请免费）", "verified": True,
         "url": "https://www.jetbrains.com/clion/download/",
         "note": "可选；CLion 自带 cmake/ninja，也可用它的工具链"},
    ],
    "vscode": [
        {"source": "微软官网", "verified": True,
         "url": "https://code.visualstudio.com/download",
         "note": "可选；配 CMake Tools / Cortex-Debug 扩展更顺手"},
    ],
    "openocd": [
        {"source": "winget (xpack) ★本机实测", "verified": True,
         "cmd": 'winget install -e --id xpack-dev-tools.openocd-xpack'},
        {"source": "xpack releases", "verified": True,
         "url": "https://github.com/xpack-dev-tools/openocd-xpack/releases"},
        {"source": "清华 github-release 镜像", "verified": False,
         "note": "实测该镜像站【不收录】xpack-dev-tools，不要指望这条路"},
    ],
}

DEFAULT_SOURCES = [
    {"name": "pypi-tuna", "url": "https://pypi.tuna.tsinghua.edu.cn/simple/pyocd/", "verified": True},
    {"name": "pypi-aliyun", "url": "https://mirrors.aliyun.com/pypi/simple/pyocd/", "verified": True},
    {"name": "github", "url": "https://github.com/xpack-dev-tools/openocd-xpack/releases", "verified": True},
    {"name": "arm-official", "url": "https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads", "verified": True},
]


# ------------------------------------------------------------------ 小工具
def run(cmd, timeout=25):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return r.returncode, r.stdout.decode("utf-8", "replace")
    except Exception as e:                              # noqa: BLE001
        return -1, str(e)


def find_project(start=None):
    """从当前目录向上找含 CMakePresets.json 或 CMakeLists.txt 的目录"""
    d = os.path.abspath(start or os.getcwd())
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "CMakePresets.json")) or \
           os.path.isfile(os.path.join(d, "CMakeLists.txt")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return None


def newest_mtime(root, exts=(".c", ".h", ".cpp", ".hpp", ".s", ".ld", ".txt", ".json")):
    newest = 0.0
    skip = {"build", ".git", "__pycache__", "Drivers", ".cmsk"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in skip]
        for fn in filenames:
            if fn.lower().endswith(exts):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dirpath, fn)))
                except OSError:
                    pass
    return newest


def list_serial_ports():
    try:
        import serial.tools.list_ports as lp
    except Exception:                                   # noqa: BLE001
        return None
    return [(p.device, p.description or "") for p in lp.comports()]


def port_busy(port, baud=115200):
    try:
        import serial
    except Exception:                                   # noqa: BLE001
        return None, "pyserial 未安装，无法判断"
    try:
        s = serial.Serial(port, baud, timeout=0.1)
        s.close()
        return False, "空闲"
    except Exception as e:                              # noqa: BLE001
        msg = str(e)
        if "Permission" in msg or "拒绝访问" in msg or "Access is denied" in msg:
            return True, "被占用"
        if "FileNotFound" in msg or "找不到" in msg or "could not open port" in msg:
            return None, "不存在"
        return None, msg[:60]


def detect_probe():
    """先问 pyocd；pyocd 不在就问系统 USB"""
    out = {"backend": None, "found": False, "detail": ""}
    pyocd = TR.find_tool("pyocd")
    if pyocd:
        rc, txt = run([pyocd, "list"], 40)
        out["backend"] = "pyocd"
        # ★ pyOCD 输出的是 "STM32 STLink"（没有连字符）；旧写法只认 "ST-Link" 会漏判
        KEYS = ("ST-Link", "STLink", "STLINK", "CMSIS-DAP", "CMSIS", "J-Link", "JLink")
        if any(k in txt for k in KEYS):
            out["found"] = True
            out["detail"] = "、".join(l.strip() for l in txt.splitlines()
                                      if any(k in l for k in KEYS))[:120]
        else:
            out["detail"] = "pyocd 未枚举到探针"
        return out
    if IS_WIN:
        rc, txt = run('powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | '
                      'Where-Object {$_.FriendlyName -match \'ST-Link|STLink|CMSIS-DAP|J-Link\'} | '
                      'Select-Object -ExpandProperty FriendlyName"', 40)
        out["backend"] = "pnp"
        names = [l.strip() for l in txt.splitlines() if l.strip()]
        out["found"] = bool(names)
        out["detail"] = "、".join(names)[:120] or "未检测到 ST-Link/CMSIS-DAP"
    return out


def stale_procs():
    names = ("pyocd", "openocd", "pyocd-gdbserver")
    hits = []
    if IS_WIN:
        rc, txt = run("tasklist", 30)
        for line in txt.splitlines():
            low = line.lower()
            if any(n in low for n in names):
                hits.append(line.strip()[:80])
    else:
        for n in names:
            rc, txt = run(["pgrep", "-af", n], 10)
            if rc == 0:
                hits += [l.strip()[:80] for l in txt.splitlines()]
    return hits


def net_probe(sources, timeout=3):
    results = []
    for s in sources:
        t0 = time.time()
        rc, txt = run('curl -sS -o NUL -m %d -w "%%{http_code}" "%s"' % (timeout, s["url"])
                      if IS_WIN else
                      'curl -sS -o /dev/null -m %d -w "%%{http_code}" "%s"' % (timeout, s["url"]),
                      timeout + 5)
        ms = int((time.time() - t0) * 1000)
        code = (txt or "").strip().splitlines()[-1][:3] if txt.strip() else "ERR"
        results.append({"name": s["name"], "url": s["url"],
                        "http": code, "ms": ms, "ok": code.startswith("2"),
                        "verified": s.get("verified")})
    return results


# ------------------------------------------------------------------ 主流程
def main(argv):
    as_json = "--json" in argv
    hints_only = "--install-hints" in argv
    do_net = "--probe-net" in argv
    do_fix = "--fix" in argv
    allow_no_probe = "--allow-no-probe" in argv
    assume_yes = "--yes" in argv or "-y" in argv

    cfg_path = None
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            cfg_path = argv[i + 1]
    if not cfg_path:
        guess = os.path.join(SKILL_ROOT, "config", "project.json")
        cfg_path = guess if os.path.isfile(guess) else None
    cfg = TR.load_project_config(cfg_path) if cfg_path else {}

    report = {"skill": "cmake-stm32-autodebug-skill",
              "when": time.strftime("%Y-%m-%d %H:%M:%S"),
              "platform": platform.platform(),
              "config": cfg_path,
              "tools": [], "openocd_scripts": None, "probe": {},
              "serial": {}, "stale": [], "project": {}, "net": [],
              "problems": [], "ok": False}

    # 1) 工具
    rows = TR.scan(cfg)
    report["tools"] = rows
    for r in rows:
        if r.get("optional"):
            continue                      # 可选软件缺失不算问题（单独提示）
        if r["need"] and not r["ok"]:
            report["problems"].append("缺少必需工具 %s（%s）" % (r["label"], r["reason"]))

    # 2) openocd scripts
    oocd = next((r["path"] for r in rows if r["tool"] == "openocd" and r["ok"]), None)
    scripts = TR.find_openocd_scripts(oocd, cfg) if oocd else None
    report["openocd_scripts"] = scripts
    if oocd and not scripts:
        report["problems"].append("找到 openocd 但定位不到 scripts 目录（interface/target 配置）")

    # 3) 探针
    probe = detect_probe()
    report["probe"] = probe
    if not probe["found"] and not allow_no_probe:
        report["problems"].append("未检测到调试探针（ST-Link/CMSIS-DAP）：%s" % probe["detail"])

    # 4) 串口
    ports = list_serial_ports()
    sp = (cfg.get("serial") or {})
    target_port = sp.get("port")
    serial_info = {"ports": ports, "target": target_port, "busy": None, "detail": ""}
    if ports is None:
        serial_info["detail"] = "pyserial 未安装（pip install pyserial）"
    elif target_port:
        busy, detail = port_busy(target_port, int(sp.get("baud", 115200)))
        serial_info["busy"], serial_info["detail"] = busy, detail
        if busy:
            report["problems"].append("串口 %s 被占用（关掉上位机/串口助手）" % target_port)
        elif busy is None:
            report["problems"].append("串口 %s 不可用：%s" % (target_port, detail))
    report["serial"] = serial_info

    # 5) 残留进程
    stale = stale_procs()
    report["stale"] = stale
    if stale:
        report["problems"].append("发现 %d 个残留 pyocd/openocd 进程（可能占着探针）" % len(stale))

    # 6) 工程
    proj = find_project()
    pinfo = {"root": proj}
    if proj:
        presets = os.path.join(proj, "CMakePresets.json")
        pinfo["presets"] = os.path.isfile(presets)
        bin_path = (cfg.get("build") or {}).get("bin")
        if bin_path:
            bp = os.path.join(proj, bin_path)
            pinfo["bin"] = bp
            pinfo["bin_exists"] = os.path.isfile(bp)
            if pinfo["bin_exists"]:
                newest = newest_mtime(proj)
                pinfo["bin_stale"] = os.path.getmtime(bp) < newest
                if pinfo["bin_stale"]:
                    report["problems"].append("产物比源码旧（需要重新编译）")
            else:
                report["problems"].append("找不到产物 %s" % bin_path)
        if not pinfo["presets"]:
            report["problems"].append("工程里没有 CMakePresets.json")
    else:
        report["problems"].append("当前目录向上找不到 CMake 工程")
    report["project"] = pinfo

    # 7) 网络源（可选）
    if do_net:
        report["net"] = net_probe((cfg.get("net") or {}).get("sources") or DEFAULT_SOURCES)

    report["ok"] = not report["problems"]

    # ---- 输出 ----
    if hints_only:
        for r in report["tools"]:
            if r["ok"]:
                continue
            print("== %s（%s）" % (r["label"], r["reason"]))
            for h in INSTALL_HINTS.get(r["tool"], []):
                tail = h.get("cmd") or h.get("url") or h.get("note", "")
                print("   [%s] %s\n        %s" % ("已验证" if h.get("verified") is True else
                                                  ("部分" if h.get("verified") == "partial" else "未验证"),
                                                  h["source"], tail))
        if report["problems"]:
            print("\n== 其他问题")
            for p in report["problems"]:
                print("   - " + p)
        return 0 if report["ok"] else 6

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 6

    print("=" * 78)
    print(" cmake-stm32-autodebug-skill · env_doctor")
    print(" 平台 %s" % report["platform"])
    print(" 配置 %s" % (report["config"] or "（未提供，走自动发现）"))
    print("=" * 78)
    for r in report["tools"]:
        mark = "OK  " if r["ok"] else ("MISS" if not r["path"] else "BAD ")
        print("[%s] %-28s %-12s %s" % (mark, r["label"], r["version_raw"] or "-",
                                       r["path"] or r["reason"]))
        if not r["ok"] and r["tool"] in INSTALL_HINTS:
            for h in INSTALL_HINTS[r["tool"]][:2]:
                print("        → %s: %s" % (h["source"], h.get("cmd") or h.get("url") or h.get("note")))
    print("-" * 78)
    opts = [r for r in rows if r.get("optional")]
    if opts:
        for r in opts:
            mark = "有  " if r["ok"] else "缺  "
            print("[OPT ] %-52s %s" % (r["label"], r["path"] or "未安装（可选，需要时再装）"))
            if not r["ok"]:
                for h in INSTALL_HINTS.get(r["tool"], [])[:1]:
                    print("        → %s: %s" % (h["source"], h.get("url") or h.get("cmd") or h.get("note", "")))
    print("-" * 78)
    print("[%s] openocd scripts: %s" % ("OK  " if scripts else "WARN", scripts or "-"))
    print("[%s] 探针: %s" % ("OK  " if probe["found"] else "MISS",
                             probe["detail"] or "-"))
    if ports:
        print("[INFO] 串口: %s" % "、".join("%s(%s)" % (d, s) for d, s in ports))
    else:
        print("[MISS] 串口: 无（pyserial 未装或没有串口设备）")
    if target_port:
        print("[%s] 目标串口 %s: %s" % ("OK  " if serial_info["busy"] is False else "WARN",
                                        target_port, serial_info["detail"]))
    if stale:
        print("[WARN] 残留进程 %d 个：%s" % (len(stale), stale[:3]))
    if proj:
        print("[INFO] 工程: %s（产物 %s）" % (proj, "存在" if pinfo.get("bin_exists") else "缺失"))
    if do_net:
        print("-" * 78)
        for n in report["net"]:
            print("[%s] %-16s %4dms  HTTP %s" % ("OK  " if n["ok"] else "FAIL",
                                                 n["name"], n["ms"], n["http"]))
    print("=" * 78)
    if report["ok"]:
        print(" 结论：环境齐全，可以进入 build/flash 闭环")
    else:
        print(" 结论：还有 %d 个问题（exit 6）" % len(report["problems"]))
        for p in report["problems"]:
            print("   - " + p)
        print(" 修好后重跑：python scripts/env_doctor.py")

    # ---- 可选：结束残留进程 ----
    if do_fix and stale:
        if not assume_yes:
            print("\n[--fix] 检测到残留进程但未带 --yes，未执行。")
        else:
            for n in ("pyocd", "openocd"):
                run("taskkill /F /IM %s.exe" % n if IS_WIN else ["pkill", "-f", n], 20)
            print("\n[--fix] 已尝试结束 pyocd/openocd 进程，请重跑体检确认。")

    return 0 if report["ok"] else 6


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
