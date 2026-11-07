"""虚拟方向盘 · 电脑端：收 UDP 包 → 预处理 → 写虚拟手柄 → 每 0.1 秒打印。

收手机样本包（传感器 + 按键位图 + 一次性标志）和配置包，交给 vwheel.steering 积分成角度，
再经 vwheel.gamepad 写进虚拟 Xbox 360 手柄；没装 vgamepad 时自动降级成只打印。
用法：python main.py [--host --port --interval --range --axis --deadzone ...]
"""

from __future__ import annotations

import argparse
import math
import socket
import struct
import sys
import time
from typing import NamedTuple

from .gamepad import GamepadOut
from .protocol import (BUTTON_CODES, CONFIG_FMT, CONFIG_SIZE, FLAG_RECALIB, FLAG_RESET,
                       SAMPLE_FMT, SAMPLE_SIZE, TYPE_CONFIG, TYPE_SAMPLE, button_label,
                       button_text)
from .steering import MAX_VALUE, RANGE_MAX, RANGE_MIN, Config, State, SteerProcessor

BAR_WIDTH = 21

SHOW_RAW = False       # --raw：状态行附带原始三轴角速度与轴外比（诊断用）


class Sample(NamedTuple):
    seq: int
    gx: float
    gy: float
    gz: float
    ax: float
    ay: float
    az: float
    t: float          # 手机端采样时间戳，Unix epoch 毫秒
    mask: int         # 按键位图
    flags: int        # 一次性标志位
    qx: float         # 姿态四元数（Android 旋转向量的格式，全 0 = 没有姿态数据）
    qy: float
    qz: float
    qw: float
    who: str          # 来源 "ip:port"

    @property
    def quat(self) -> tuple[float, float, float, float]:
        return (self.qx, self.qy, self.qz, self.qw)


def _safe_stdout() -> None:
    """Windows 控制台默认编码是 GBK，输出了 GBK 编不出来的符号会直接抛 UnicodeEncodeError。
    把两个输出流的错误处理改成 replace，保证 demo 不会因为一个装饰符号崩掉。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def find_local_ips() -> list[str]:
    """猜一下本机的局域网 IP，方便告诉用户手机端该填什么。"""
    ips: set[str] = set()
    # UDP connect 不会真的发包，但能让系统选出走默认路由的那张网卡的 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    # 127.0.0.1 是回环，手机连不到，不当成提示
    return sorted(ip for ip in ips if not ip.startswith("127."))


def steer_bar(value: int, width: int = BAR_WIDTH) -> str:
    """把 -32767..32767 画成一根带中心线的条，一眼看出打了几度。"""
    pos = int(round((value / MAX_VALUE + 1.0) / 2.0 * (width - 1)))
    pos = max(0, min(width - 1, pos))
    cells = ["-"] * width
    cells[width // 2] = "|"
    cells[pos] = "#"
    return "".join(cells)


def print_button_edges(old_mask: int, new_mask: int) -> None:
    """对比位图变化，打印按下/松开。位图是状态，所以丢几个包也不会漏掉最终状态。"""
    for bit in sorted(BUTTON_CODES):
        flag = 1 << (bit - 1)
        was, now = bool(old_mask & flag), bool(new_mask & flag)
        if now and not was:
            print(f"           ↓ 按下 {button_label(bit):<2s}  ", flush=True)
        elif was and not now:
            print(f"           ↑ 松开 {button_label(bit):<2s}  ", flush=True)


def att_text(st: State) -> str:
    """姿态参考的状态。ok = 正在用系统四元数做慢修正，- = 没有姿态数据/已关闭。"""
    if not st.att_ok:
        return "姿态=-"
    return f"姿态=ok e={st.att_err:+5.1f}°"


def axis_split(smp: Sample | None, n: tuple[float, float, float] | None) -> str:
    """把原始角速度拆成「沿转向轴」和「垂直于转向轴」两部分（--raw）。

    垂直分量不参与积分，只会白白浪费角度；它的相对大小就是轴错位角的正切：
    tan(错位角) = 轴外 / 轴上，而错位角 α 会让积分结果整体缩水 cos(α) 倍。
    """
    if smp is None or n is None:
        return ""
    par = smp.gx * n[0] + smp.gy * n[1] + smp.gz * n[2]
    px = smp.gx - par * n[0]
    py = smp.gy - par * n[1]
    pz = smp.gz - par * n[2]
    perp = math.sqrt(px * px + py * py + pz * pz)
    ratio = perp / abs(par) if abs(par) > 0.05 else 0.0
    return (f"  raw=({smp.gx:+.2f},{smp.gy:+.2f},{smp.gz:+.2f})"
            f" 轴外={ratio:.2f}x")


def format_state(st: State, mask: int, smp: Sample | None = None,
                 axis_vec: tuple[float, float, float] | None = None) -> str:
    if not st.calibrated:
        return "校准中…（手机保持静止 1 秒）"
    if not st.axis_locked:
        # 自由轴模式还没识别出旋转轴：先让用户左右打一次方向
        return (f"识别旋转轴…请慢慢左右各打一次方向"
                f"（已 {st.axis_samples:3d} 帧，能量 {st.axis_energy:5.1f}）"
                f"  键={button_text(mask)}")
    extra = axis_split(smp, axis_vec) if SHOW_RAW else ""
    return (f"{steer_bar(st.value)}  角度={st.angle_deg:+7.1f}°  "
            f"值={st.value:+6d}  角速度={st.rate:+6.2f}  键={button_text(mask)}  "
            f"{att_text(st)}{extra}")


def axis_locked_text(st: State) -> str:
    """旋转轴锁定那一瞬间打印的信息：轴上分量 + 一致度。"""
    n = st.axis_vec
    if n is None:
        return "           [ok] 旋转轴已锁定  "
    return (f"           [ok] 旋转轴已锁定 n=({n[0]:+.2f}, {n[1]:+.2f}, {n[2]:+.2f})  "
            f"一致度={st.axis_quality:.2f}（1.00 = 转得很干净）  ")


def range_deg_arg(text: str) -> int:
    """--range 的值：单边角度，90..900，允许小数（四舍五入成整数度）。"""
    try:
        v = int(round(float(text)))
    except ValueError:
        raise argparse.ArgumentTypeError("角度范围要是数字，例如 540")
    if v < RANGE_MIN or v > RANGE_MAX:
        raise argparse.ArgumentTypeError(
            f"角度范围要在 {RANGE_MIN}..{RANGE_MAX} 之间（单边角度：540 = ±540°，总量程 1080°）")
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="虚拟方向盘 电脑端：接收 + 预处理 + 写虚拟 Xbox 手柄")
    ap.add_argument("--host", "-H", default="0.0.0.0", help="监听地址，默认 0.0.0.0（所有网卡）")
    ap.add_argument("--port", "-p", type=int, default=8888, help="监听端口，默认 8888")
    ap.add_argument("--interval", "-i", type=float, default=0.1, help="打印间隔（秒），默认 0.1")
    ap.add_argument("--range", "-r", type=range_deg_arg, default=540,
                    help=f"单边角度范围 {RANGE_MIN}..{RANGE_MAX}（±N°，无级），默认 540")
    ap.add_argument("--axis", "-a", choices=["x", "y", "z", "auto"], default="z",
                    help="转向轴：x/y/z 固定，auto = 自动识别旋转轴（手机斜着贴也能用）")
    ap.add_argument("--deadzone", type=float, default=0.02, help="死区（rad/s），默认 0.02")
    ap.add_argument("--smoothing", type=float, default=0.30, help="平滑 0~0.95，默认 0.30")
    ap.add_argument("--self-center", type=float, default=0.0,
                    help="自动回正速率（1/秒），0 = 关闭")
    ap.add_argument("--no-att", action="store_true",
                    help="关掉姿态慢修正（只用陀螺积分；车内磁干扰很严重时用）")
    ap.add_argument("--no-zupt", action="store_true",
                    help="关掉 ZUPT 静止零偏重估（一般不需要关）")
    ap.add_argument("--no-gamepad", action="store_true",
                    help="不写虚拟手柄，只打印（没装 vgamepad 时也能跑）")
    ap.add_argument("--invert", action="store_true",
                    help="转向反打（打左变成打右）")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="转向增益，默认 1.0；<1 更钝，>1 更容易打满")
    ap.add_argument("--stick", choices=["lx", "ly", "rx", "ry"], default="lx",
                    help="转向映射到哪个摇杆轴，默认 lx（左摇杆 X）")
    ap.add_argument("--raw", action="store_true",
                    help="状态行里附带原始三轴角速度与「轴外比」，用来查角度偏小的原因")
    args = ap.parse_args(argv)
    _safe_stdout()
    global SHOW_RAW
    SHOW_RAW = args.raw

    interval = max(0.01, args.interval)
    cfg = Config(
        range_deg=args.range,
        axis={"x": 0, "y": 1, "z": 2, "auto": 3}[args.axis],
        deadzone=args.deadzone,
        smoothing=args.smoothing,
        self_center=args.self_center,
    ).normalized()
    proc = SteerProcessor(cfg, zupt_enabled=not args.no_zupt, att_enabled=not args.no_att)
    pad = GamepadOut(enabled=not args.no_gamepad, invert=args.invert,
                     gain=args.gain, stick=args.stick)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.host, args.port))
        sock.setblocking(False)  # 用“收完所有包再睡到下一个 tick”的方式驱动循环
    except OSError as exc:
        print(f"[x] 绑定 {args.host}:{args.port} 失败：{exc}", file=sys.stderr)
        print("    端口被占用的话换一个：python main.py --port 9000", file=sys.stderr)
        return 1

    ips = find_local_ips()
    print("=" * 100)
    print(f"虚拟方向盘 · 电脑端   监听 {args.host}:{args.port}   每 {interval:g}s 打印一次")
    if ips:
        print("手机端『电脑 IP』请填：" + "  或  ".join(ips))
    else:
        print("手机端『电脑 IP』请填：本机局域网 IP（用 ipconfig 自己看一下）")
    print(f"当前参数：{cfg.describe()}   （手机端设置页会实时覆盖）")
    print(f"防漂：ZUPT={'开' if proc.zupt_enabled else '关'}   "
          f"姿态慢修正={'开' if proc.att_enabled else '关'}")
    print(f"手柄输出：{pad.describe()}")
    if cfg.is_free_axis:
        print("旋转轴=自动：开始后请把手机当方向盘慢慢左右各打一次，识别完成这里会提示")
    print("先另开一个终端跑  python tools/simulate.py     Ctrl+C 退出")
    print("=" * 100)

    total = 0             # 收到的样本包总数
    lost = 0              # 按 seq 缺口估算的丢包
    bad = 0               # 长度/类型不对的包
    last_seq: int | None = None
    window_count = 0      # 当前打印窗口内的包数
    hist: list[tuple[int, float]] = []   # 最近约 1 秒的 (包数, 时长)，算平稳的 pkt/s
    rate = 0.0
    last_sample: Sample | None = None
    t0: float | None = None      # 手机端第一包的时间戳，打印时换算成相对秒数
    mask = 0              # 当前按键位图
    prev_flags = 0        # 上一包的标志位（用来只触发一次）
    last_rx = 0.0
    idle_notified = False       # 一次断流里“这格没数据”只提示一次
    last_stale_print = 0.0      # “已断流”每秒只刷一次
    axis_reported = False       # 自由轴锁定信息只打印一次
    att_reported = False        # 姿态接入提示只打印一次
    pad_safe = False            # 断流后是否已经把方向盘回中（每次断流只做一次）
    zupt_reported = 0           # 上次提示过的 ZUPT 次数
    last_zupt_print = 0.0
    last_att_warn = 0.0
    started = time.monotonic()
    last_print = started
    next_tick = started + interval

    try:
        while True:
            # 1) 把这一瞬间积压的包全部收干净（非阻塞）
            while True:
                try:
                    data, addr = sock.recvfrom(2048)
                except BlockingIOError:
                    break
                except OSError:
                    # Windows 上对端端口关掉时会抛 ConnectionReset，忽略即可
                    break

                if len(data) < 4:
                    bad += 1
                    continue
                kind, = struct.unpack_from("<i", data, 0)

                if kind == TYPE_CONFIG:
                    if len(data) != CONFIG_SIZE:
                        bad += 1
                        continue
                    _, rng, axis, dz, sm, sc = struct.unpack(CONFIG_FMT, data)
                    cfg = Config(rng, axis, dz, sm, sc).normalized()
                    proc.set_config(cfg)
                    axis_reported = False
                    print(f"           [cfg] 配置更新：{cfg.describe()}  ", flush=True)
                    continue

                if kind != TYPE_SAMPLE:
                    bad += 1
                    continue
                if len(data) != SAMPLE_SIZE:
                    bad += 1
                    continue

                (_, seq, gx, gy, gz, ax, ay, az, t, new_mask, flags,
                 qx, qy, qz, qw) = struct.unpack(SAMPLE_FMT, data)
                total += 1
                window_count += 1
                idle_notified = False
                last_rx = time.monotonic()
                last_sample = Sample(seq, gx, gy, gz, ax, ay, az, t, new_mask, flags,
                                     qx, qy, qz, qw, f"{addr[0]}:{addr[1]}")
                if t0 is None:
                    t0 = t

                # 2) 丢包统计
                if last_seq is not None:
                    step = seq - last_seq
                    if step > 1:
                        lost += step - 1
                last_seq = seq

                # 3) 按键边沿（位图是状态，靠前后对比得到“按下/松开”）
                if new_mask != mask:
                    print_button_edges(mask, new_mask)
                    mask = new_mask

                # 4) 一次性标志（手机点了「回正」/「校准」）
                fresh = flags & ~prev_flags
                prev_flags = flags
                if fresh & FLAG_RESET:
                    proc.zero_angle()
                    print("           [回正] 角度已归零（手机点了「回正」）  ", flush=True)
                if fresh & FLAG_RECALIB:
                    proc.begin_calibration()
                    axis_reported = False
                    att_reported = False
                    print("           [校准] 重新校准零偏…（手机保持静止 1 秒）  ", flush=True)

                # 5) 预处理（四元数一起传进去，供姿态慢修正用）
                st_now = proc.push(t, gx, gy, gz, ax, ay, az, last_sample.quat)

                # 6) 写虚拟手柄：-32767..32767 归一化成 -1..1，按键靠位图 diff
                #    每包写一次（约 50Hz），比 0.1 秒打印快得多，手感才跟得上
                pad.update(st_now.value / MAX_VALUE, mask)
                pad_safe = False

            # 7) 到点打印一行
            now = time.monotonic()
            if now >= next_tick:
                # 用两次打印之间的真实间隔算速率（不能用 now-next_tick+interval，
                # 那样会把“睡过头”的误差算成窗口变长，速率会系统性偏低）
                elapsed = now - last_print
                last_print = now
                next_tick += interval
                if next_tick <= now:  # 落后太多就别追了
                    next_tick = now + interval

                hist.append((window_count, elapsed))
                hist_time = sum(e for _, e in hist)
                while hist_time > 1.2 and len(hist) > 1:
                    hist_time -= hist[0][1]
                    hist.pop(0)
                if hist_time > 0:
                    rate = sum(c for c, _ in hist) / hist_time

                stamp = f"[{now - started:7.1f}s]"

                if total == 0:
                    extra = "   （收到未知格式的包，检查两端版本是否一致）" if bad else ""
                    print(f"{stamp} 等待数据…还没有收到任何包{extra}", flush=True)
                elif now - last_rx > 1.0:
                    if not pad_safe:
                        # 手机断了但车还在跑：方向回中、按键松开，比卡在打死更安全
                        pad_safe = True
                        pad.failsafe()
                    if now - last_stale_print >= 1.0:
                        last_stale_print = now
                        print(f"{stamp} 已断流 {now - last_rx:4.1f}s   累计收包={total} 丢包={lost}",
                              flush=True)
                elif window_count == 0:
                    if not idle_notified:
                        idle_notified = True
                        seq_now = last_sample.seq if last_sample else 0
                        print(f"{stamp} 这一格没收到新包（最后 seq={seq_now}，"
                              f"距上次 {now - last_rx:4.2f}s）", flush=True)
                else:
                    smp = last_sample
                    assert smp is not None
                    st = proc.state()
                    if proc.cfg.is_free_axis and st.axis_locked and not axis_reported:
                        axis_reported = True
                        print(axis_locked_text(st), flush=True)
                    if st.att_ok and not att_reported:
                        att_reported = True
                        print("           [ok] 姿态参考已接入：用系统四元数做慢修正"
                              "（时间常数约 40 秒，只治漂移，不改变手感）  ", flush=True)
                    if st.zupt_updates != zupt_reported and now - last_zupt_print >= 3.0:
                        zupt_reported = st.zupt_updates
                        last_zupt_print = now
                        print(f"           [zupt] 静止零偏重估 #{st.zupt_updates}："
                              f"当前零偏={st.bias:+.5f} rad/s  ", flush=True)
                    if (st.att_ok and abs(st.att_err) > 20.0
                            and now - last_att_warn >= 5.0):
                        last_att_warn = now
                        print(f"           [!] 姿态与积分相差 {st.att_err:+.1f}°，"
                              f"暂时不修正（多半是磁干扰或刚接入）  ", flush=True)
                    t_rel = (smp.t - t0) / 1000.0 if t0 is not None else 0.0
                    print(f"{stamp} {rate:5.1f}pkt/s 丢包={lost:<4d} ±{proc.cfg.range_deg}° "
                          f"{format_state(st, mask, smp, proc.axis_unit)}  t=+{t_rel:7.2f}s",
                          flush=True)

                window_count = 0
            else:
                time.sleep(min(next_tick - now, 0.05))

    except KeyboardInterrupt:
        who = f"{last_sample.who}" if last_sample else "无"
        print(f"\n退出。累计收包 {total} 个，估算丢包 {lost} 个，来源 {who}")
        print(pad.stats())
        if mask:
            print(f"退出时仍按着：{button_text(mask)}")
        return 0
    finally:
        pad.close()
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
