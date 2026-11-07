"""转向角处理：陀螺仪角速度 → 方向盘角度 → -32767..32767。

纯计算模块，不碰网络和手柄：校准零偏 → 投影到转向轴 → 死区 → 一阶低通 → 积分 → 回正 → 限幅 → 映射。
自动轴模式用角速度样本的协方差主方向（PCA 幂迭代）估出旋转轴 n，因为 ω = Ω·n，投影即真实角速度。
防漂两层：ZUPT（静止时重估零偏）与姿态四元数慢修正（PI 观测器，宁可不用也不被磁干扰拽走）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_VALUE = 32767      # 最终映射目标：-32767 .. 32767
BIAS_SECONDS = 1.0     # 启动后静止多久用来估算零偏
BIAS_MIN_SAMPLES = 10  # 至少这么多帧才敢算零偏
MAX_DT = 0.25          # 单帧积分步长上限（秒）
RESYNC_GAP = 0.5       # 两帧间隔超过这个（秒）就认为断流过，重新对齐时间、不积分
RANGE_MIN, RANGE_MAX = 90, 900   # 单边角度范围：90 = ±90°（总量程 180°），900 = ±900°（总量程 1800°），中间无级
AXIS_NAMES = ("X", "Y", "Z", "自动")
FREE_AXIS = 3          # axis == 3 表示「自动识别旋转轴」

# —— 自由轴识别参数 ——
AXIS_GATE = 0.15       # 只有 |ω-bias| 超过这个角速度的样本才拿去估轴（静止噪声不参与）
AXIS_MIN_SAMPLES = 24  # 至少要这么多有效样本
AXIS_MIN_ENERGY = 8.0  # Σ|ω|² 的能量门槛（1 rad/s 转 0.5 秒大约 25）
AXIS_MIN_RATIO = 0.75  # 主特征值 / 总能量，低于它说明转得不够一致，继续攒
AXIS_TIMEOUT_MS = 6000  # 攒了这么久（手机时间戳）还没达标，就用现有样本硬锁一个

# —— ZUPT：静止零偏重估 ——
ZUPT_GATE = 0.04       # 偏离零偏小于它就算「静止」（0.04 rad/s ≈ 2.3°/s）
ZUPT_DWELL_MS = 600.0  # 连续静止这么久才更新一次零偏（0.6 秒）
ZUPT_ALPHA = 0.30      # 零偏低通的步长，小一点更稳

# —— 姿态慢修正 ——
ATT_KP = 0.05          # 比例增益（1/秒）：err=1° 时每秒把角度拉 0.05°
ATT_KI = ATT_KP * ATT_KP / 4.0   # 积分增益（1/秒²），取 Kp²/4 让二阶系统临界阻尼
ATT_BIAS_MAX = 0.02    # 积分项最多学到 ±0.02 rad/s（≈1.15°/s）的零偏
ATT_MAX_ERR = 45.0     # 误差超过这么多度就认为姿态不可信，这一帧不修正
ATT_RATE_GATE = 15.0   # 角速度超过这么多度/秒就不修正（融合器延迟会让 err 失真）
ATT_MIN_NORM2 = 0.9    # 四元数模长²的合法区间：手机端没有姿态数据时发全 0
ATT_MAX_NORM2 = 1.1


@dataclass
class Config:
    """处理参数。手机端设置页会把这些值下发下来覆盖默认值。"""

    range_deg: int = 540        # 单边角度范围：90..900 之间任意整数（无级）
    axis: int = 2               # 转向轴：0=X 1=Y 2=Z 3=自动识别
    deadzone: float = 0.02      # 死区，rad/s
    smoothing: float = 0.30     # 平滑，0 = 不平滑，0.95 = 很迟钝
    self_center: float = 0.0    # 自动回正速率（1/秒），0 = 关闭

    def normalized(self) -> "Config":
        """把可能来自网络的脏值夹到合法范围，避免除零 / 轴越界。"""
        rng = int(round(self.range_deg))
        rng = max(RANGE_MIN, min(RANGE_MAX, rng))
        return Config(
            range_deg=rng,
            axis=max(0, min(FREE_AXIS, int(self.axis))),
            deadzone=max(0.0, min(1.0, float(self.deadzone))),
            smoothing=max(0.0, min(0.95, float(self.smoothing))),
            self_center=max(0.0, min(10.0, float(self.self_center))),
        )

    @property
    def axis_name(self) -> str:
        return AXIS_NAMES[self.axis]

    @property
    def is_free_axis(self) -> bool:
        return self.axis == FREE_AXIS

    def describe(self) -> str:
        return (f"±{self.range_deg}° 轴={self.axis_name} 死区={self.deadzone:.3f}"
                f" 平滑={self.smoothing:.2f} 回正={self.self_center:.2f}")


@dataclass
class State:
    """一次 push 之后的状态快照，打印用。"""

    calibrated: bool
    angle_deg: float
    value: int
    rate: float   # 过滤后的转向角速度（rad/s）
    bias: float   # 当前零偏（投影到转向轴上的分量）
    axis_locked: bool = True          # 自由轴模式下：旋转轴识别出来了没
    axis_vec: tuple[float, float, float] | None = None
    axis_quality: float = 0.0         # 主方向占总能量的比例，越接近 1 越干净
    axis_samples: int = 0             # 已经攒了多少个用于识别的样本
    axis_energy: float = 0.0

    # —— ZUPT ——
    zupt_updates: int = 0             # 静止零偏重估做了几次
    static_ms: float = 0.0            # 当前已经连续静止多久

    # —— 姿态慢修正 ——
    att_ok: bool = False              # 有没有可用的姿态数据
    att_angle: float = 0.0            # 姿态给出的角度（和 angle_deg 同一基准）
    att_err: float = 0.0              # 姿态角 − 积分角（度）
    att_bias: float = 0.0             # 积分项学到的额外零偏（rad/s）
    att_fixes: int = 0                # 实际做过修正的帧数


# ---------------------------------------------------------------------------
# 小工具：三维向量 + 四元数
# ---------------------------------------------------------------------------
def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: tuple[float, float, float],
           b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit(a: tuple[float, float, float]) -> tuple[float, float, float]:
    n = _norm(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def quat_mul(a: tuple[float, float, float, float],
             b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """四元数乘法 a⊗b（先 b 后 a），格式 (x, y, z, w)，和 Android 的旋转向量一致。"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def quat_from_axis_angle(axis: tuple[float, float, float],
                         angle_rad: float) -> tuple[float, float, float, float]:
    """绕单位轴 axis 转 angle_rad 的四元数。"""
    n = _unit(axis)
    h = angle_rad * 0.5
    s = math.sin(h)
    return (n[0] * s, n[1] * s, n[2] * s, math.cos(h))


def quat_to_matrix(q: tuple[float, float, float, float]) -> list[list[float]]:
    """四元数 → 3×3 旋转矩阵（机体 → 世界）。"""
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def mat_vec(m: list[list[float]],
            v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def pick_axis(gx: float, gy: float, gz: float, axis: int) -> float:
    """手动模式：直接取某个机身轴。"""
    if axis == 0:
        return gx
    if axis == 1:
        return gy
    return gz


def _principal_direction(cov: list[list[float]]) -> tuple[float, float, float]:
    """3×3 协方差矩阵的主特征向量（幂迭代，起点取对角元最大的轴）。"""
    diag = [cov[0][0], cov[1][1], cov[2][2]]
    k = diag.index(max(diag))
    v = [0.0, 0.0, 0.0]
    v[k] = 1.0
    for _ in range(32):
        w = [0.0, 0.0, 0.0]
        for i in range(3):
            w[i] = cov[i][0] * v[0] + cov[i][1] * v[1] + cov[i][2] * v[2]
        norm = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
        if norm < 1e-12:
            break
        v = [w[0] / norm, w[1] / norm, w[2] / norm]
    return (v[0], v[1], v[2])


class SteerProcessor:
    def __init__(self, cfg: Config | None = None,
                 zupt_enabled: bool = True,
                 att_enabled: bool = True):
        self.cfg = (cfg or Config()).normalized()
        self.zupt_enabled = zupt_enabled
        self.att_enabled = att_enabled
        self.angle_deg = 0.0
        self._rate = 0.0
        self._bias = 0.0
        self._bias_sum = [0.0, 0.0, 0.0]
        self._bias_vec: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._bias_n = 0
        self._bias_t0: float | None = None
        self._t_prev: float | None = None
        self.calibrated = False
        # 自由轴识别用
        self._cov = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        self._axis_energy = 0.0
        self._axis_n = 0
        self._axis_t0: float | None = None
        self._axis_vec: tuple[float, float, float] | None = None
        self._axis_quality = 0.0
        if not self.cfg.is_free_axis:
            self._axis_vec = None  # 手动模式不锁轴，state() 里会显示成已锁定
        # ZUPT
        self._static_ms = 0.0
        self._zupt_updates = 0
        # 姿态
        self._quat_in: tuple[float, float, float, float] | None = None
        self._q: tuple[float, float, float, float] | None = None
        self._att_frame_n: tuple[float, float, float] | None = None   # 世界系转向轴 N
        self._att_ref: tuple[float, float, float] = (1.0, 0.0, 0.0)
        self._att_v: tuple[float, float, float] = (1.0, 0.0, 0.0)     # 机体系参考向量 v⊥n
        self._att_unwrapped: float = 0.0
        self._att_prev: float | None = None
        self._att_zero: float = 0.0
        self._att_base: float = 0.0
        self._att_ok = False
        self._att_err = 0.0
        self._att_bias = 0.0
        self._att_fixes = 0

    # ---- 控制 ----
    def set_config(self, cfg: Config) -> None:
        old_axis = self.cfg.axis
        self.cfg = cfg.normalized()
        if self.cfg.axis != old_axis:
            # 换了轴，之前积出来的角度没有意义了，重新开始
            self._reset_axis()
            self.angle_deg = 0.0
            self._rate = 0.0
            self._t_prev = None
            self._att_bias = 0.0
            self._att_reset_frame()
            self._ensure_att_frame()
        self._clamp()

    def begin_calibration(self) -> None:
        """重新采零偏 + 重新识别旋转轴（都会把角度归零，因为积分基准变了）。"""
        self._bias_sum = [0.0, 0.0, 0.0]
        self._bias_vec = (0.0, 0.0, 0.0)
        self._bias_n = 0
        self._bias_t0 = None
        self._bias = 0.0
        self._rate = 0.0
        self._t_prev = None
        self.angle_deg = 0.0
        self.calibrated = False
        self._static_ms = 0.0
        self._att_bias = 0.0
        self._reset_axis()
        self._att_reset_frame()

    def zero_angle(self) -> None:
        """只把角度清零，不动零偏。等于「把当前姿势当成方向盘正中」。"""
        self.angle_deg = 0.0
        self._att_set_origin()

    def _reset_axis(self) -> None:
        self._cov = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        self._axis_energy = 0.0
        self._axis_n = 0
        self._axis_t0 = None
        self._axis_vec = None
        self._axis_quality = 0.0

    # ---- 姿态相关的小工具 ----
    @property
    def axis_unit(self) -> tuple[float, float, float] | None:
        """转向轴在机体系里的单位向量（手动模式就用那根坐标轴）。"""
        if self.cfg.is_free_axis:
            return self._axis_vec
        base = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
        return base[self.cfg.axis]

    def _att_reset_frame(self) -> None:
        """丢掉姿态框架（重新校准时用），下一帧会重新建立。"""
        self._att_frame_n = None
        self._att_prev = None
        self._att_unwrapped = 0.0
        self._att_zero = 0.0
        self._att_base = 0.0
        self._att_ok = False
        self._att_err = 0.0

    def _ensure_att_frame(self) -> None:
        """建立「世界系转向轴 N = R(q)·n + 一个跟着轮子转的参考向量」，并把姿态角基准对齐到当前角度。"""
        n = self.axis_unit
        q = self._q
        if n is None or q is None:
            self._att_frame_n = None
            return
        R = quat_to_matrix(q)
        N = _unit(mat_vec(R, n))
        # 选一个和 n 垂直的机身参考向量 v：v 跟着轮子转，它的世界方向绕 N 的角度就是轮角
        idx = min(range(3), key=lambda i: abs(n[i]))
        e = [0.0, 0.0, 0.0]
        e[idx] = 1.0
        v = _unit(_cross(n, (e[0], e[1], e[2])))
        ref = _unit(mat_vec(R, v))
        ref = _unit((ref[0] - N[0] * _dot(ref, N),
                     ref[1] - N[1] * _dot(ref, N),
                     ref[2] - N[2] * _dot(ref, N)))
        self._att_frame_n = N
        self._att_v = v
        self._att_ref = ref
        self._att_prev = None      # 换了参考系，下一帧重新起算
        self._att_ok = False
        self._att_set_origin()

    def _att_set_origin(self) -> None:
        """把「当前姿态角」定义为「当前积分角度」。"""
        self._att_zero = self._att_unwrapped
        self._att_base = self.angle_deg

    def _update_attitude(self, dt: float, rate_deg: float) -> None:
        """用最新姿态算角度，并用 PI 观测器把积分结果慢慢拉过去。"""
        q = self._quat_in
        if q is None:
            return
        n2 = q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]
        if not (ATT_MIN_NORM2 <= n2 <= ATT_MAX_NORM2):
            # 模长不在 1 附近：手机端没有姿态数据（全 0）或者是坏值
            self._q = None
            self._att_ok = False
            return
        self._q = _unit4(q)
        if self.cfg.is_free_axis and self._axis_vec is None:
            return  # 轴还没识别，先把四元数存着
        if self._att_frame_n is None:
            self._ensure_att_frame()
            if self._att_frame_n is None:
                return

        N = self._att_frame_n
        w = mat_vec(quat_to_matrix(self._q), self._att_v)
        # 理论上 w 恒垂直于 N；投影一次去掉数值误差和手机的其它小动作
        w = (w[0] - N[0] * _dot(w, N),
             w[1] - N[1] * _dot(w, N),
             w[2] - N[2] * _dot(w, N))
        wn = _norm(w)
        if wn < 0.2:
            return  # 退化姿态，这一帧不用
        w = (w[0] / wn, w[1] / wn, w[2] / wn)

        ref = self._att_ref
        ang = math.atan2(_dot(_cross(ref, w), N), _dot(ref, w))
        if self._att_prev is None:
            self._att_prev = ang
            self._att_unwrapped = ang
            self._att_zero = ang
        else:
            d = ang - self._att_prev
            d = (d + math.pi) % (2.0 * math.pi) - math.pi   # 解缠绕：取最短路径
            self._att_unwrapped += d
            self._att_prev = ang

        self._att_ok = True
        att_angle = math.degrees(self._att_unwrapped - self._att_zero) + self._att_base
        err = att_angle - self.angle_deg
        err = (err + 180.0) % 360.0 - 180.0
        self._att_err = err

        if not self.att_enabled or dt <= 0.0:
            return
        if abs(err) > ATT_MAX_ERR:
            return      # 差太多，八成是磁干扰/姿态刚恢复，先别动
        if abs(rate_deg) > ATT_RATE_GATE:
            return      # 转得快的时候融合器延迟会让 err 失真，此时不修正

        # 比例项：直接把角度往参考拉（不会振荡，但单独用会留稳态偏差）
        d_angle = ATT_KP * err * dt
        if d_angle != 0.0:
            self.angle_deg += d_angle
            self._att_fixes += 1
            self._clamp()
        # 积分项：把残差记成零偏估计，这样漂移本身被消掉（否则会一直有稳态偏差）
        self._att_bias -= math.radians(ATT_KI * err * dt)
        if self._att_bias > ATT_BIAS_MAX:
            self._att_bias = ATT_BIAS_MAX
        elif self._att_bias < -ATT_BIAS_MAX:
            self._att_bias = -ATT_BIAS_MAX

    # ---- 主流程 ----
    def push(self, t_ms: float, gx: float, gy: float, gz: float,
             ax: float = 0.0, ay: float = 0.0, az: float = 0.0,
             quat: tuple[float, float, float, float] | None = None) -> State:
        self._quat_in = quat

        # 1) 先攒够 1 秒静止数据，估零偏（现在是向量，三个轴都记）
        if not self.calibrated:
            if self._bias_t0 is None:
                self._bias_t0 = t_ms
            if t_ms >= (self._bias_t0 or 0.0):
                self._bias_sum[0] += gx
                self._bias_sum[1] += gy
                self._bias_sum[2] += gz
                self._bias_n += 1
            if self._bias_n >= BIAS_MIN_SAMPLES and (t_ms - (self._bias_t0 or t_ms)) >= BIAS_SECONDS * 1000.0:
                n = float(self._bias_n)
                self._bias_vec = (self._bias_sum[0] / n, self._bias_sum[1] / n, self._bias_sum[2] / n)
                self.calibrated = True
                self._t_prev = t_ms
                self.angle_deg = 0.0
                self._ensure_att_frame()
            return self._finish(0.0, 0.0)

        # 2) 自由轴模式：还没识别出旋转轴，就先攒样本
        if self.cfg.is_free_axis and self._axis_vec is None:
            self._accumulate_axis(t_ms, gx, gy, gz)
            if self._axis_vec is None:
                return self._finish(0.0, 0.0)
            # 刚锁定：这段时间用户是在打方向，不能把它积分进去，从现在重新开始
            self.angle_deg = 0.0
            self._rate = 0.0
            self._t_prev = t_ms
            self._ensure_att_frame()
            return self._finish(0.0, 0.0)

        # 3) 时间步长：用手机端时间戳，断流太久就重新对齐（不能把几秒的角速度一次积分掉）
        if self._t_prev is None:
            self._t_prev = t_ms
            return self._finish(0.0, 0.0)
        dt = (t_ms - self._t_prev) / 1000.0
        if dt <= 0.0:
            return self._finish(0.0, 0.0)
        self._t_prev = t_ms
        if dt > RESYNC_GAP:
            return self._finish(0.0, 0.0)
        if dt > MAX_DT:
            dt = MAX_DT

        # 4) ZUPT：连续静止就把当前读数当零偏修正（治「零偏慢慢变」）
        self._update_zupt(gx, gy, gz, dt)

        # 5) 投影到转向轴 → 扣零偏
        raw, bias = self._project(gx, gy, gz)
        self._bias = bias

        # 6) 死区 → 一阶低通
        rate = raw - bias
        if abs(rate) < self.cfg.deadzone:
            rate = 0.0
        alpha = 1.0 - self.cfg.smoothing
        self._rate += alpha * (rate - self._rate)

        # 7) 积分 + 回正 + 限幅
        self.angle_deg += math.degrees(self._rate * dt)
        if self.cfg.self_center > 0.0:
            self.angle_deg -= self.angle_deg * min(1.0, self.cfg.self_center * dt)
        self._clamp()
        return self._finish(dt, math.degrees(self._rate))

    # ---- 内部 ----
    def _finish(self, dt: float, rate_deg: float) -> State:
        """每次 push 结尾都走这里：先喂姿态，再吐状态快照。"""
        self._update_attitude(dt, rate_deg)
        return self.state()

    def _update_zupt(self, gx: float, gy: float, gz: float, dt: float) -> None:
        if not self.zupt_enabled:
            return
        w = (gx - self._bias_vec[0], gy - self._bias_vec[1], gz - self._bias_vec[2])
        if _norm(w) >= ZUPT_GATE:
            self._static_ms = 0.0
            return
        self._static_ms += dt * 1000.0
        if self._static_ms < ZUPT_DWELL_MS:
            return
        # 静止了；读数里剩下的就是零偏的漂移量，慢慢挪过去（不要一步到位，防抖）
        a = ZUPT_ALPHA
        self._bias_vec = (self._bias_vec[0] + a * (gx - self._bias_vec[0]),
                          self._bias_vec[1] + a * (gy - self._bias_vec[1]),
                          self._bias_vec[2] + a * (gz - self._bias_vec[2]))
        self._zupt_updates += 1
        self._static_ms = 0.0

    def _project(self, gx: float, gy: float, gz: float) -> tuple[float, float]:
        """把机体角速度投影到转向轴上，返回 (原始投影值, 零偏在轴上的分量)。"""
        if self.cfg.is_free_axis:
            n = self._axis_vec
            if n is None:
                return 0.0, 0.0
            return (gx * n[0] + gy * n[1] + gz * n[2],
                    _dot(self._bias_vec, n) + self._att_bias)
        axis = self.cfg.axis
        raw = pick_axis(gx, gy, gz, axis)
        return raw, self._bias_vec[axis] + self._att_bias

    def _accumulate_axis(self, t_ms: float, gx: float, gy: float, gz: float) -> None:
        """把「真的在转」的角速度样本累进协方差，并尝试锁定旋转轴。"""
        w = (gx - self._bias_vec[0], gy - self._bias_vec[1], gz - self._bias_vec[2])
        mag2 = w[0] * w[0] + w[1] * w[1] + w[2] * w[2]
        if mag2 < AXIS_GATE * AXIS_GATE:
            return  # 基本静止，噪声不参与估轴
        if self._axis_t0 is None:
            self._axis_t0 = t_ms
        for i in range(3):
            for j in range(3):
                self._cov[i][j] += w[i] * w[j]
        self._axis_energy += mag2
        self._axis_n += 1

        if self._axis_n < AXIS_MIN_SAMPLES:
            return
        waited = t_ms - (self._axis_t0 if self._axis_t0 is not None else t_ms)
        enough = self._axis_energy >= AXIS_MIN_ENERGY
        if not enough and waited < AXIS_TIMEOUT_MS:
            return

        n = _principal_direction(self._cov)
        lam = (n[0] * (self._cov[0][0] * n[0] + self._cov[0][1] * n[1] + self._cov[0][2] * n[2])
               + n[1] * (self._cov[1][0] * n[0] + self._cov[1][1] * n[1] + self._cov[1][2] * n[2])
               + n[2] * (self._cov[2][0] * n[0] + self._cov[2][1] * n[1] + self._cov[2][2] * n[2]))
        trace = self._cov[0][0] + self._cov[1][1] + self._cov[2][2]
        ratio = (lam / trace) if trace > 1e-9 else 0.0
        if ratio < AXIS_MIN_RATIO and waited < AXIS_TIMEOUT_MS:
            return  # 转得还不够一致（比如手抖、或者同时在摇晃），继续攒
        if ratio <= 0.0:
            return

        # 特征向量的正负是任意的；定个规矩：绝对值最大的分量为正，这样同一套贴法每次算出来的方向一致
        idx = max(range(3), key=lambda i: abs(n[i]))
        if n[idx] < 0:
            n = (-n[0], -n[1], -n[2])

        self._axis_vec = n
        self._axis_quality = ratio

    def _clamp(self) -> None:
        limit = float(self.cfg.range_deg)
        if self.angle_deg > limit:
            self.angle_deg = limit
        elif self.angle_deg < -limit:
            self.angle_deg = -limit

    # ---- 输出 ----
    @property
    def value(self) -> int:
        v = int(round(self.angle_deg / float(self.cfg.range_deg) * MAX_VALUE))
        return max(-MAX_VALUE, min(MAX_VALUE, v))

    def state(self) -> State:
        locked = (not self.cfg.is_free_axis) or (self._axis_vec is not None)
        return State(
            calibrated=self.calibrated,
            angle_deg=self.angle_deg,
            value=self.value,
            rate=self._rate,
            bias=self._bias,
            axis_locked=locked,
            axis_vec=self._axis_vec,
            axis_quality=self._axis_quality,
            axis_samples=self._axis_n,
            axis_energy=self._axis_energy,
            zupt_updates=self._zupt_updates,
            static_ms=self._static_ms,
            att_ok=self._att_ok,
            att_angle=math.degrees(self._att_unwrapped - self._att_zero) + self._att_base
            if self._att_ok else 0.0,
            att_err=self._att_err,
            att_bias=self._att_bias,
            att_fixes=self._att_fixes,
        )


def _unit4(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


# ---------------------------------------------------------------------------
# 不带手机也能验算：python -m vwheel.steering
# ---------------------------------------------------------------------------
def _quiet(proc: SteerProcessor, t: float, frames: int = 60) -> float:
    for _ in range(frames):
        proc.push(t, 0.0, 0.0, 0.0)
        t += 20.0
    return t


def selftest() -> int:
    # 1) 单轴：1 rad/s 转 1 秒 → 57.30°
    proc = SteerProcessor(Config(range_deg=540, smoothing=0.0, deadzone=0.0))
    t = _quiet(proc, 1_760_000_000_000.0)
    st = proc.state()
    print(f"校准: calibrated={st.calibrated} bias={st.bias:+.5f}")
    for _ in range(50):
        proc.push(t, 0.0, 0.0, 1.0)
        t += 20.0
    st = proc.state()
    print(f"1 rad/s 转 1 秒: 角度={st.angle_deg:+.2f}° 值={st.value:+6d} (理论 57.30° / 3477)")

    # 2) ±90° 模式超限应被夹住
    proc2 = SteerProcessor(Config(range_deg=90, smoothing=0.0, deadzone=0.0))
    t = _quiet(proc2, 1_760_000_000_000.0)
    for _ in range(250):
        proc2.push(t, 0.0, 0.0, 1.0)
        t += 20.0
    st2 = proc2.state()
    print(f"±90° 模式超限: 角度={st2.angle_deg:+.1f}° 值={st2.value:+6d} (应被夹在 90° / 32767)")

    # 3) 倾斜 30° 安装：真实旋转轴 n=(0, sin30, cos30)
    tilt = math.radians(30.0)
    n = (0.0, math.sin(tilt), math.cos(tilt))
    omega = 1.0  # rad/s 绕 n 转

    def turn(proc_: SteerProcessor, t0: float, seconds: float) -> float:
        frames = int(seconds * 50)
        for _ in range(frames):
            proc_.push(t0, omega * n[0], omega * n[1], omega * n[2])
            t0 += 20.0
        return t0

    # 3a) 手动 axis=z（旧做法）：只拿到 cos30 = 0.866 倍 → 角度偏小
    manual = SteerProcessor(Config(range_deg=540, axis=2, smoothing=0.0, deadzone=0.0))
    t = _quiet(manual, 1_760_000_000_000.0)
    t = turn(manual, t, 1.0)
    print(f"倾斜 30° + 手动 axis=Z: 角度={manual.state().angle_deg:+.2f}° "
          f"(只有理论值的 {manual.state().angle_deg / 57.2958:.2f} 倍)")

    # 3b) 自由轴：先转一会儿让它识别出旋转轴（锁定那一刻角度会清零），
    #     之后再看「再转 1 秒」涨了多少 —— 这个增量应该正好是 57.30°。
    free = SteerProcessor(Config(range_deg=540, axis=FREE_AXIS, smoothing=0.0, deadzone=0.0))
    t = _quiet(free, 1_760_000_000_000.0)
    t = turn(free, t, 1.0)          # 这一秒用来识别旋转轴
    st = free.state()
    print(f"自由轴识别: locked={st.axis_locked} n=({st.axis_vec[0]:+.3f},{st.axis_vec[1]:+.3f},"
          f"{st.axis_vec[2]:+.3f}) 一致度={st.axis_quality:.2f} 样本={st.axis_samples} "
          f"（真实 n=(0.000,+0.500,+0.866)）")
    angle_before = st.angle_deg
    t = turn(free, t, 1.0)
    st = free.state()
    delta = st.angle_deg - angle_before
    print(f"倾斜 30° + 自由轴:      再转 1 秒增量={delta:+.2f}° (理论 57.30°) "
          f"当前角度={st.angle_deg:+.2f}° 值={st.value:+6d}")

    # 4) 姿态慢修正：校准之后陀螺零偏又漂了 0.02 rad/s（≈1.15°/s），
    #    纯积分 60 秒会漂到 +69°；接上姿态参考后应该被拉回来。
    print()
    injected = 0.02
    q0 = (0.0, 0.0, 0.0, 1.0)      # 机身与世界对齐：转向轴就是 z
    raw_p = SteerProcessor(Config(range_deg=540, axis=2, smoothing=0.0, deadzone=0.0),
                           zupt_enabled=False, att_enabled=False)
    att_p = SteerProcessor(Config(range_deg=540, axis=2, smoothing=0.0, deadzone=0.0),
                           zupt_enabled=False, att_enabled=True)
    t = _quiet(raw_p, 1_760_000_000_000.0)
    _quiet(att_p, 1_760_000_000_000.0)
    marks = {3000: "60 秒", 9000: "180 秒"}
    for frame in range(1, 9001):   # 180 秒，手机一直没动，只有零偏在漂
        raw_p.push(t, 0.0, 0.0, injected)
        att_p.push(t, 0.0, 0.0, injected, 0.0, 0.0, 1.0, q0)
        t += 20.0
        if frame in marks:
            st_raw, st_att = raw_p.state(), att_p.state()
            print(f"假零偏 {injected} rad/s 静止 {marks[frame]}："
                  f"纯积分={st_raw.angle_deg:+7.2f}°   "
                  f"姿态慢修正={st_att.angle_deg:+6.2f}°  "
                  f"err={st_att.att_err:+5.2f}°  学到零偏={st_att.att_bias:+.5f} rad/s "
                  f"(真值 {injected:+.5f})")

    # 5) ZUPT：静止 3 秒，零偏应该被拉回去
    z = SteerProcessor(Config(range_deg=540, axis=2, smoothing=0.0, deadzone=0.0),
                       zupt_enabled=True, att_enabled=False)
    t = _quiet(z, 1_760_000_000_000.0)
    for _ in range(150):
        z.push(t, 0.0, 0.0, 0.01)   # 静止但零偏漂到 0.01
        t += 20.0
    st_z = z.state()
    print(f"ZUPT 静止 3 秒：重估 {st_z.zupt_updates} 次，零偏={st_z.bias:+.5f} rad/s，"
          f"角度={st_z.angle_deg:+.2f}°（应接近 0）")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())
