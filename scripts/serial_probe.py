#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serial_probe —— 串口发命令 / 收应答 / 断言

用法示例：
  python scripts/serial_probe.py --port COM14 --cmd PING --expect "@PONG"
  python scripts/serial_probe.py --port COM14 --cmd "STAT 1" --read-seconds 0.8
  python scripts/serial_probe.py --port COM14 --cmd "@RX" --expect-re "ovf=0.*pend=0"
  python scripts/serial_probe.py --list

退出码：
  0 匹配成功（或未给 --expect* 时"收到非空数据"）
  4 串口打不开 / 超时没匹配（对应 skill 的 exit 4）
"""
from __future__ import annotations

import argparse
import re
import sys
import time


def parse_arg(argv):
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--port", help="串口名，如 COM14 / /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--cmd", action="append", default=[], help="要发送的命令（可重复），自动加 CRLF")
    ap.add_argument("--expect", help="包含匹配（子串）")
    ap.add_argument("--expect-re", help="正则匹配")
    ap.add_argument("--expect-hex", help="二进制帧头匹配，如 \"AA 55\"（可带空格/冒号）")
    ap.add_argument("--timeout", type=float, default=3.0, help="等待期望的总超时（秒）")
    ap.add_argument("--read-seconds", type=float, default=0.0,
                    help="不做断言，只读这么久（秒）；与 --expect* 互斥")
    ap.add_argument("--raw", action="store_true", help="打印原始字节（排查编码/二进制）")
    ap.add_argument("--list", action="store_true", help="只列出串口")
    return ap.parse_args(argv)


def list_ports():
    try:
        import serial.tools.list_ports as lp
    except Exception as e:                                  # noqa: BLE001
        print("[ERR] 需要 pyserial: python -m pip install pyserial  (%s)" % e)
        return 4
    ports = list(lp.comports())
    if not ports:
        print("[MISS] 没有可用串口")
        return 4
    for p in ports:
        print("%-10s %s" % (p.device, p.description or ""))
    return 0


def main(argv):
    a = parse_arg(argv)

    if a.list:
        return list_ports()

    try:
        import serial
    except Exception as e:                                  # noqa: BLE001
        print("[ERR] 需要 pyserial: python -m pip install pyserial  (%s)" % e)
        return 4

    if not a.port:
        print("[ERR] 缺少 --port（用 --list 查看可用串口）")
        return 4

    try:
        ser = serial.Serial(a.port, a.baud, timeout=0.05, write_timeout=1.0)
    except Exception as e:                                  # noqa: BLE001
        msg = str(e)
        print("[ERR] 打不开 %s: %s" % (a.port, msg))
        if "Permission" in msg or "拒绝访问" in msg:
            print("      串口被占用：关掉上位机/串口助手，或 env_doctor.py 看 serial.busy")
        elif "FileNotFound" in msg or "找不到" in msg:
            print("      端口不存在：检查 USB 线/驱动，或换口")
        return 4

    hexpat = None
    if a.expect_hex:
        hx = re.sub(r"[^0-9a-fA-F]", "", a.expect_hex)
        if len(hx) < 2 or len(hx) % 2:
            print("[ERR] --expect-hex 需要偶数个十六进制字符，如 \"AA 55\"")
            return 4
        hexpat = bytes.fromhex(hx)

    buf = bytearray()
    try:
        time.sleep(0.05)
        ser.reset_input_buffer()
        for c in a.cmd:
            ser.write((c + "\r\n").encode("utf-8"))
            ser.flush()
            time.sleep(0.02)
            print("[TX] %s" % c)

        if a.read_seconds > 0 and not (a.expect or a.expect_re or hexpat):
            t0 = time.time()
            while time.time() - t0 < a.read_seconds:
                buf += ser.read(4096)
        else:
            t0 = time.time()
            pat = re.compile(a.expect_re) if a.expect_re else None
            while time.time() - t0 < a.timeout:
                buf += ser.read(4096)
                txt = buf.decode("utf-8", "replace")
                if pat and pat.search(txt):
                    break
                if a.expect and a.expect in txt:
                    break
                if hexpat is not None and hexpat in bytes(buf):
                    break
                time.sleep(0.01)
    finally:
        try:
            ser.close()
        except Exception:                                   # noqa: BLE001
            pass

    if a.raw:
        print("[RX-HEX] %s" % bytes(buf).hex(" "))
    txt = buf.decode("utf-8", "replace")
    if txt:
        for line in txt.splitlines():
            if line.strip():
                print("[RX] %s" % line)
    else:
        print("[RX] （无数据）")

    if hexpat is not None:
        n = bytes(buf).count(hexpat) if len(hexpat) >= 2 else 0
        ok = n > 0
        print("[%s] 二进制帧头 %s 出现 %d 次（共 %d 字节 / %.2fs）"
              % ("PASS" if ok else "FAIL", hexpat.hex(" ").upper(), n, len(buf), a.timeout))
        return 0 if ok else 4

    if a.expect or a.expect_re:
        ok = (a.expect in txt) if a.expect else bool(re.search(a.expect_re, txt))
        print("[%s] 期望 %s" % ("PASS" if ok else "FAIL", a.expect or a.expect_re))
        return 0 if ok else 4

    if a.read_seconds > 0:
        return 0 if buf else 4

    return 0 if buf else 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
