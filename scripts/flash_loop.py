#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flash_loop —— 编译 → 烧录 → 串口令牌 的闭环（退出码契约见 SKILL.md）

    python scripts/flash_loop.py --project . --config config/project.json
    python scripts/flash_loop.py --project . --dry-run        # 只编译 + 新鲜度 + 预检
    python scripts/flash_loop.py --project . --backend pyocd
    python scripts/flash_loop.py --project . --skip-precheck

退出码：0 通过 / 1 编译 / 2 烧录 / 3 运行时崩溃 / 4 串口 / 5 停机 / 6 环境

★ 两条硬顺序（改不得）：
   1) 先 halt → 再开串口 → 最后 resume     否则漏掉启动横幅 → 每轮假超时
   2) 烧录失败立即中止                     否则串口读到旧固件 → 结论全反
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    import toolresolve as TR
except Exception as e:                                      # noqa: BLE001
    print("[FATAL] 需要 scripts/toolresolve.py: %s" % e)
    sys.exit(6)

IS_WIN = (os.name == "nt")
EXIT = {"pass": 0, "build": 1, "flash": 2, "runtime": 3, "serial": 4, "stall": 5, "env": 6}


# ------------------------------------------------------------------ 工具
def run(cmd, timeout=600, cwd=None, env=None):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, cwd=cwd, env=env)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def report(proj, data):
    d = os.path.join(proj, "build", ".cmsk")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "diagnostic_report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return p


def load_cfg(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ 步骤
def step_build(proj, cfg, preset):
    cmake = TR.find_tool("cmake") or "cmake"
    rc, out = run([cmake, "--build", "--preset", preset], 900, cwd=proj)
    errs = [l for l in out.splitlines()
            if re.search(r"error:|undefined reference|No such file|region .* overflowed", l, re.I)]
    info = {"step": "build", "preset": preset, "rc": rc, "errors": errs[:20]}
    if rc != 0:
        info["tail"] = out.splitlines()[-30:]
        return EXIT["build"], info
    return EXIT["pass"], info


def resolve_artifacts(proj, cfg):
    b = (cfg.get("build") or {})
    elf = b.get("elf")
    binp = b.get("bin")
    if elf:
        elf = os.path.join(proj, elf)
    if binp:
        binp = os.path.join(proj, binp)
    return elf, binp


def step_flash(proj, cfg, backend):
    b = (cfg.get("build") or {})
    t = (cfg.get("target") or {})
    elf, binp = resolve_artifacts(proj, cfg)
    target_cfg = t.get("openocd_target") or "target/stm32h7x.cfg"
    iface = t.get("openocd_interface") or "interface/stlink.cfg"

    if backend == "openocd":
        oocd = TR.find_tool("openocd")
        if not oocd:
            return EXIT["env"], {"step": "flash", "error": "openocd 未找到"}
        scripts = TR.find_openocd_scripts(oocd, cfg)
        if not scripts:
            return EXIT["env"], {"step": "flash", "error": "openocd scripts 目录定位失败"}
        art = elf if (elf and os.path.isfile(elf)) else binp
        if not art:
            return EXIT["env"], {"step": "flash", "error": "找不到 elf/bin 产物"}
        prog = 'program "%s" verify reset exit' % art.replace("\\", "/")
        if art.endswith(".bin"):
            prog = 'program "%s" 0x08000000 verify reset exit' % art.replace("\\", "/")
        cmd = [oocd, "-s", scripts, "-f", iface, "-f", target_cfg, "-c", prog]
        rc, out = run(cmd, 300, cwd=proj)
        ok = rc == 0 and "** Programming Finished **" in out or (rc == 0 and "shutdown command invoked" in out)
        return (EXIT["pass"] if ok else EXIT["flash"],
                {"step": "flash", "backend": "openocd", "cmd": " ".join(cmd),
                 "rc": rc, "tail": out.splitlines()[-15:]})

    # pyocd
    py = TR.find_tool("pyocd") or TR.find_tool("python")
    chip = t.get("chip") or "stm32h723xx"
    art = binp if (binp and os.path.isfile(binp)) else elf
    if not art:
        return EXIT["env"], {"step": "flash", "error": "找不到 elf/bin 产物"}
    base = [py, "-m", "pyocd"] if py.endswith(("python.exe", "python")) else [py]
    cmd = base + ["flash", "-t", chip, "--connect", "under-reset", art]
    rc, out = run(cmd, 300, cwd=proj)
    ok = rc == 0
    return (EXIT["pass"] if ok else EXIT["flash"],
            {"step": "flash", "backend": "pyocd", "cmd": " ".join(cmd), "rc": rc,
             "tail": out.splitlines()[-15:]})


def step_serial(cfg, do_go=None):
    """返回 (code, info)；顺序：halt 已由 flash 保证 -> 开串口 -> resume -> 等令牌"""
    s = (cfg.get("serial") or {})
    port = s.get("port")
    baud = int(s.get("baud", 115200))
    probe = s.get("probe_cmd", "PING")
    token = s.get("token", "@PONG")
    timeout = float(s.get("timeout_s", 5))
    if not port:
        return EXIT["env"], {"step": "serial", "error": "config.serial.port 未配置"}

    try:
        import serial
    except Exception:                                       # noqa: BLE001
        return EXIT["env"], {"step": "serial", "error": "pyserial 未安装"}

    try:
        ser = serial.Serial(port, baud, timeout=0.05, write_timeout=1.0)
    except Exception as e:                                  # noqa: BLE001
        return EXIT["serial"], {"step": "serial", "error": "打开 %s 失败: %s" % (port, e)}

    try:
        ser.reset_input_buffer()
        if do_go:                                            # 释放内核（在串口已打开之后）
            try:
                do_go()
            except Exception as e:                           # noqa: BLE001
                return EXIT["serial"], {"step": "serial", "error": "resume 失败: %s" % e}
        ser.write((probe + "\r\n").encode())
        ser.flush()
        buf = b""
        t0 = time.time()
        while time.time() - t0 < timeout:
            buf += ser.read(4096)
            if token in buf.decode("utf-8", "replace"):
                return EXIT["pass"], {"step": "serial", "token": token, "got": buf.decode("utf-8", "replace")[:200]}
            time.sleep(0.02)
        return EXIT["serial"], {"step": "serial", "error": "等不到令牌 %s" % token,
                                "got": buf.decode("utf-8", "replace")[:200]}
    finally:
        try:
            ser.close()
        except Exception:                                    # noqa: BLE001
            pass


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    ap.add_argument("--config", default=None)
    ap.add_argument("--preset", default=None)
    ap.add_argument("--backend", choices=["openocd", "pyocd"], default=None)
    ap.add_argument("--dry-run", action="store_true", help="只做 build+新鲜度+预检")
    ap.add_argument("--skip-precheck", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    proj = os.path.abspath(a.project)
    cfg_path = a.config or os.path.join(SKILL_ROOT, "config", "project.json")
    cfg = load_cfg(cfg_path)
    preset = a.preset or (cfg.get("build") or {}).get("preset") or "Release"
    backend = a.backend or (cfg.get("flash") or {}).get("backend") or "openocd"

    rep = {"skill": "cmake-stm32-autodebug-skill", "when": time.strftime("%Y-%m-%d %H:%M:%S"),
           "project": proj, "preset": preset, "backend": backend, "steps": []}

    # ③ 预检（先做：环境不对后面都是白费）
    if not a.skip_precheck:
        doctor = os.path.join(HERE, "env_doctor.py")
        rc, out = run([sys.executable, doctor, "--json"], 180, cwd=proj)
        try:
            d = json.loads(out)
        except Exception:                                   # noqa: BLE001
            d = {"ok": False, "problems": ["env_doctor 输出无法解析"]}
        rep["steps"].append({"step": "precheck", "rc": rc, "ok": d.get("ok"),
                             "problems": d.get("problems", [])[:6]})
        if rc != 0:
            print("[precheck] 环境不齐（exit 6），先修：")
            for p in d.get("problems", [])[:8]:
                print("   - " + p)
            report(proj, rep)
            return EXIT["env"]

    # ① 编译
    code, info = step_build(proj, cfg, preset)
    rep["steps"].append(info)
    if code != 0:
        print("[build] 失败（exit 1）")
        for e in info.get("errors", [])[:10]:
            print("   " + e)
        report(proj, rep)
        return code
    print("[build] OK")

    # ② 产物新鲜度
    elf, binp = resolve_artifacts(proj, cfg)
    art = binp if (binp and os.path.isfile(binp)) else elf
    if not art or not os.path.isfile(art):
        rep["steps"].append({"step": "artifact", "error": "产物不存在"})
        print("[artifact] 找不到产物（exit 6）")
        report(proj, rep)
        return EXIT["env"]
    h1 = sha256(art)
    rep["artifact"] = {"path": art, "sha256": h1}
    print("[artifact] %s  sha256=%s…" % (os.path.basename(art), h1[:16]))

    if a.dry_run:
        report(proj, rep)
        print("[dry-run] 到预检+编译为止，不再烧录")
        return EXIT["pass"]

    # ④⑤ 烧录（halt 由 `reset`/under-reset 保证）
    code, info = step_flash(proj, cfg, backend)
    rep["steps"].append(info)
    if code != 0:
        print("[flash] 失败（exit 2）——这是硬件/环境问题，不要改业务代码")
        for l in info.get("tail", [])[-8:]:
            print("   " + l)
        report(proj, rep)
        return code
    print("[flash] OK（后端 %s）" % backend)

    # ⑥⑦⑧ 串口（先开串口再 resume 的顺序在 step_serial 内部保证）
    code, info = step_serial(cfg)
    rep["steps"].append(info)
    if code != 0:
        print("[serial] 失败（exit 4）: %s" % info.get("error", ""))
        report(proj, rep)
        return code
    print("[serial] 收到令牌 %s" % info.get("token"))

    # ⑨ 失败签名去重
    sig = "%d|%s" % (code, rep["steps"][-1].get("error", ""))
    hist = os.path.join(proj, "build", ".cmsk", "last_signature.txt")
    prev = ""
    if os.path.isfile(hist):
        prev = open(hist, encoding="utf-8").read().strip()
    os.makedirs(os.path.dirname(hist), exist_ok=True)
    open(hist, "w", encoding="utf-8").write(sig)

    rp = report(proj, rep)
    print("[done] 全通过（exit 0）  报告: %s" % rp)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    return EXIT["pass"]


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
