"""假数据发送器：不接手机也能验证电脑端 main.py 的接收 + 预处理。

按手机端 vw-udp 插件完全相同的格式发包（样本 104 字节 / 配置 36 字节，小端），
还会按时间表演一遍按键（A / LB+RT / X+Y+L3 / D-pad）和「回正」「校准」标志。
四元数与陀螺仪严格自洽：轮子绕世界轴 N 以 θ(t) 转 → 陀螺仪读数 θ'(t)·n，四元数 Rot(N, θ(t))。
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vwheel.protocol import (CONFIG_FMT, FLAG_RECALIB, FLAG_RESET, SAMPLE_FMT, TYPE_CONFIG,
                             TYPE_SAMPLE, mask_bit)
from vwheel.steering import quat_from_axis_angle, quat_mul

BTN_A, BTN_B, BTN_X, BTN_Y = 1, 2, 3, 4
BTN_LB, BTN_RB, BTN_LT, BTN_RT = 5, 6, 7, 8
BTN_L3, BTN_L4 = 9, 10
BTN_UP, BTN_DOWN, BTN_LEFT, BTN_RIGHT = 11, 12, 13, 14

OMEGA = 1.2      # 摆动幅度（rad/s）


def schedule_mask(t: float) -> int:
    """按时间造按键动作，方便看电脑端的“按下 / 松开”边沿。"""
    if 2.0 <= t < 3.0:
        return mask_bit(BTN_A)
    if 4.0 <= t < 5.0:
        return mask_bit(BTN_LB) | mask_bit(BTN_RT)
    if 7.0 <= t < 8.0:
        return mask_bit(BTN_L3) | mask_bit(BTN_X) | mask_bit(BTN_Y)
    if 9.0 <= t < 10.0:
        return mask_bit(BTN_UP) | mask_bit(BTN_RIGHT)
    return 0


def om_at(t: float) -> float:
    """摆动角速度（rad/s）。开头 1.5 秒和 16 秒附近停着不动：
    开头要留出电脑端 1 秒零偏校准的时间（手机真机上用户这时也是静止的），
    16 秒那次是「重新校准」，同样得先停住，否则零偏会把运动吸进去。"""
    if t < 1.5:
        return 0.0
    if 15.9 <= t < 17.4:
        return 0.0
    return OMEGA * math.sin(t)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="虚拟方向盘 假数据发送器")
    ap.add_argument("--host", "-H", default="127.0.0.1", help="目标 IP，默认本机")
    ap.add_argument("--port", "-p", type=int, default=8888, help="目标端口，默认 8888")
    ap.add_argument("--hz", type=float, default=50.0, help="发送频率，默认 50Hz（和手机一致）")
    ap.add_argument("--range", "-r", type=int, default=540,
                    help="下发的单边角度范围 90..900（±N°，无级），默认 540")
    ap.add_argument("--axis", "-a", choices=["x", "y", "z", "auto"], default="auto",
                    help="下发的转向轴，默认 auto（自动识别旋转轴）")
    ap.add_argument("--tilt", "-t", type=float, default=30.0,
                    help="模拟手机相对旋转轴倾斜多少度，默认 30（0 = 完全对齐机身 z）")
    ap.add_argument("--att-bias", type=float, default=0.0,
                    help="给陀螺仪注入的假零偏（rad/s），用来验证姿态慢修正，默认 0")
    ap.add_argument("--no-quat", action="store_true",
                    help="四元数发全 0，模拟手机没有姿态数据")
    ap.add_argument("--no-buttons", action="store_true", help="不模拟按键")
    args = ap.parse_args(argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    period = 1.0 / args.hz
    seq = 0
    t0 = time.monotonic()

    axis_code = {"x": 0, "y": 1, "z": 2, "auto": 3}[args.axis]
    tilt = math.radians(args.tilt)
    # 旋转轴在机身坐标里的方向：倾斜 0° 时就是 (0,0,1)，倾斜 30° 时是 (0,0.5,0.866)
    n = (0.0, math.sin(tilt), math.cos(tilt))

    # 先发一包配置，电脑端会打印「配置更新」
    sock.sendto(struct.pack(CONFIG_FMT, TYPE_CONFIG, args.range, axis_code, 0.02, 0.30, 0.0),
                (args.host, args.port))
    print(f"向 {args.host}:{args.port} 以 {args.hz:g}Hz 发假数据（±{args.range}°，轴={args.axis}，"
          f"倾斜 {args.tilt:g}°，n=({n[0]:.2f},{n[1]:.2f},{n[2]:.2f})，"
          f"{'无姿态四元数' if args.no_quat else '带姿态四元数'}，"
          f"假零偏 {args.att_bias:+.3f} rad/s，"
          f"{'带按键' if not args.no_buttons else '不带按键'}），Ctrl+C 停止")

    angle = 0.0      # 累计转角（rad）。用实际 dt 累加，保证陀螺仪和四元数严格自洽
    prev_t = 0.0

    while True:
        seq += 1
        t = time.monotonic() - t0
        dt = t - prev_t
        prev_t = t
        # 角速度：绕 n 摆动 + 一点手抖
        om = om_at(t)
        angle += om * dt
        gx = om * n[0] + 0.05 * math.sin(t * 3.0)
        gy = om * n[1] + 0.02 * math.cos(t * 0.7)
        gz = om * n[2]
        # 假零偏：只加在陀螺仪上，不动四元数（四元数代表"真实姿态"）
        gx += args.att_bias * n[0]
        gy += args.att_bias * n[1]
        gz += args.att_bias * n[2]

        # 加速度计：假装手机平放，重力全在 z 轴（单位 g）
        ax = 0.01 * math.sin(t * 5.0)
        ay = 0.01 * math.cos(t * 4.0)
        az = 1.0 + 0.005 * math.sin(t * 2.0)

        # 真实姿态：绕世界轴 n 转了 angle
        if args.no_quat:
            qx = qy = qz = qw = 0.0
        else:
            q = quat_mul(quat_from_axis_angle(n, angle), (0.0, 0.0, 0.0, 1.0))
            qx, qy, qz, qw = q

        t_ms = time.time() * 1000.0
        mask = 0 if args.no_buttons else schedule_mask(t)
        flags = 0
        # 第 10 秒点一次「回正」，第 16 秒点一次「校准」，各带 3 包（≈60ms）
        if 10.0 <= t < 10.06:
            flags |= FLAG_RESET
        if 16.0 <= t < 16.06:
            flags |= FLAG_RECALIB

        sock.sendto(struct.pack(SAMPLE_FMT, TYPE_SAMPLE, seq,
                                gx, gy, gz, ax, ay, az, t_ms, mask, flags,
                                qx, qy, qz, qw),
                    (args.host, args.port))

        # 按绝对时间排程，否则 sleep 的误差会累积，实际频率会掉到 46Hz 左右
        wait = t0 + seq * period - time.monotonic()
        if wait > 0:
            time.sleep(wait)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已停止发送")
