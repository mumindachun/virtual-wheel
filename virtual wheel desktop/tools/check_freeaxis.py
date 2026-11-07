"""开发自检：一键起 main.py + tools/simulate.py，跑 20 秒，只打印关键事件。

不用双击两个终端，适合改完 vwheel/steering.py 之后回归一下：
    python tools/check_freeaxis.py
    python tools/check_freeaxis.py --tilt 0 --axis z --seconds 10
它做的事：起接收端（打印间隔临时改成 1 秒，避免刷屏）→ 起假数据发送器 → 等若干秒
→ 从接收端输出里挑出「配置更新 / 校准 / 旋转轴 / 按键边沿 / 归零 / 断流」这些关键行打印。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("配置更新", "校准", "旋转轴", "归零", "断流", "pkt/s")


def _safe_stdout() -> None:
    """Windows 控制台是 GBK，子进程输出里解码失败的替换字符会直接抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _safe_stdout()
    ap = argparse.ArgumentParser(description="main.py + tools/simulate.py 一键联调")
    ap.add_argument("--port", type=int, default=8902)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--tilt", default="30")
    ap.add_argument("--axis", default="auto")
    args = ap.parse_args()

    # 子进程默认按控制台编码（GBK）写管道，父进程按 UTF-8 读就会变成乱码，
    # 所以显式让两个子进程都输出 UTF-8
    child_env = dict(os.environ, PYTHONIOENCODING="utf-8")

    recv = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--port", str(args.port),
         "-i", "1.0", "--no-gamepad"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1, env=child_env)
    lines: list[str] = []

    def pump() -> None:
        assert recv.stdout is not None
        for line in recv.stdout:
            lines.append(line.rstrip("\n"))

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    time.sleep(1.2)
    send = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "simulate.py"), "--port", str(args.port),
         "--tilt", args.tilt, "--axis", args.axis],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=child_env)
    time.sleep(max(1.0, args.seconds))
    send.terminate()
    time.sleep(0.5)
    recv.terminate()
    try:
        recv.wait(timeout=5)
    except subprocess.TimeoutExpired:
        recv.kill()

    keep = [ln for ln in lines if any(k in ln for k in KEYS)]
    print("\n".join(keep[-30:]))
    locked = sum(1 for ln in keep if "旋转轴已锁定" in ln)
    print(f"\n[小结] 旋转轴锁定 {locked} 次（默认跑满 20 秒时正常是 2 次：开始 1 次 + 第 16 秒重新校准后 1 次）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
