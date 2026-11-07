"""虚拟 Xbox 360 手柄输出（vgamepad + ViGEmBus）。

vgamepad 延迟导入：没装包 / 驱动没起 / --no-gamepad 时降级成「只打印」，不影响收数据。
映射：转向 → 摇杆轴，按键位图 → press/release，LT/RT → 模拟扳机；0.0 表示回中。

用法：
    python -m vwheel.gamepad            # 用假后端验证映射逻辑，不需要驱动
    python -m vwheel.gamepad --real     # 真机：摇杆扫一遍 + 按 A/LT
"""

from __future__ import annotations

from .protocol import BUTTON_CODES, BUTTON_ENUM, mask_bit

STICKS = ("lx", "ly", "rx", "ry")


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


class GamepadOut:
    """把转向值 + 按键位图写进虚拟 Xbox 手柄。

    后端状态：
        backend == "vgamepad"  真的连上了虚拟手柄
        backend == "off"       没装 vgamepad / 驱动缺失 / 用户加了 --no-gamepad

    用法（cli.py 里）：
        pad = GamepadOut(enabled=True, invert=False, gain=1.0, stick="lx")
        pad.update(steer_norm, mask)      # 每个样本包调一次，内部做边沿 diff
        pad.failsafe()                    # 断流时回中 + 松键
        pad.close()                       # 退出时 reset，避免手柄卡在某个状态
    """

    def __init__(self, enabled: bool = True, invert: bool = False,
                 gain: float = 1.0, stick: str = "lx") -> None:
        self.backend = "off"
        self.note = ""
        self.pad = None
        self._vg = None
        self.invert = bool(invert)
        self.gain = float(gain)
        self.stick = stick if stick in STICKS else "lx"
        self.mask = 0
        self.updates = 0
        self.button_events = 0
        self.errors = 0
        self._last_steer_axis = 0.0

        if not enabled:
            self.note = "已关闭（--no-gamepad）：只打印，不写手柄"
            return
        try:
            import vgamepad as vg  # 延迟导入：没装也不影响收数据
        except Exception as exc:                       # ImportError / DLL 加载失败
            self.note = f"没装 vgamepad（{type(exc).__name__}）：pip install vgamepad"
            return
        try:
            self.pad = vg.VX360Gamepad()
        except Exception as exc:                       # ViGEmBus 驱动没装 / 服务没起
            self.note = (f"创建虚拟手柄失败（ViGEmBus 驱动没装或服务没起？）：{exc}")
            return
        self._vg = vg
        self.backend = "vgamepad"
        self.note = "虚拟 Xbox 360 手柄已连接（vgamepad + ViGEmBus）"

    # ------------------------------------------------------------------ 状态
    @property
    def active(self) -> bool:
        return self.backend == "vgamepad"

    def describe(self) -> str:
        return self.note

    def stats(self) -> str:
        if not self.active:
            return "手柄未连接"
        return f"手柄已更新 {self.updates} 帧，按键事件 {self.button_events} 次"

    # ------------------------------------------------------------------ 映射
    def _steer_to_axis(self, steer_norm: float) -> float:
        v = _clamp(steer_norm * self.gain)
        if self.invert:
            v = -v
        # 摇杆是圆的，但转向只需要一根轴；轻微量化掉抖动（<0.4% 视为 0）
        if abs(v) < 0.004:
            v = 0.0
        return v

    def _apply_stick(self, v: float) -> None:
        pad = self.pad
        if self.stick == "lx":
            pad.left_joystick_float(x_value_float=v, y_value_float=0.0)
        elif self.stick == "ly":
            pad.left_joystick_float(x_value_float=0.0, y_value_float=v)
        elif self.stick == "rx":
            pad.right_joystick_float(x_value_float=v, y_value_float=0.0)
        else:
            pad.right_joystick_float(x_value_float=0.0, y_value_float=v)

    def _enum(self, name: str):
        cls = getattr(self._vg, "XUSB_BUTTON", None)
        if cls is None:
            raise AttributeError("vgamepad 里没有 XUSB_BUTTON")
        return getattr(cls, name)

    def _press(self, code: int, down: bool) -> None:
        enum_name = BUTTON_ENUM.get(code)
        if enum_name is None:
            return                      # LT/RT 走 left/right_trigger_float，不走 press_button
        btn = self._enum(enum_name)
        if down:
            self.pad.press_button(button=btn)
        else:
            self.pad.release_button(button=btn)
        self.button_events += 1

    # ------------------------------------------------------------------ 对外
    def update(self, steer_norm: float, mask: int) -> None:
        """每个样本包调一次：转向 + 按键边沿 + 扳机，然后提交一帧。"""
        if not self.active:
            return
        try:
            v = self._steer_to_axis(steer_norm)
            self._apply_stick(v)
            self._last_steer_axis = v

            # 按键：位图是状态，靠前后 diff 得到按下/松开，丢包也不会卡键
            changed = mask ^ self.mask
            if changed:
                for code in BUTTON_CODES:
                    flag = mask_bit(code)
                    if changed & flag:
                        self._press(code, bool(mask & flag))
                self.mask = mask

            # 扳机：Xbox 的 LT/RT 是 0..1 的模拟量，这里给满行程
            self.pad.left_trigger_float(value_float=1.0 if mask & mask_bit(7) else 0.0)
            self.pad.right_trigger_float(value_float=1.0 if mask & mask_bit(8) else 0.0)

            self.pad.update()
            self.updates += 1
        except Exception as exc:       # 驱动被卸载、手柄被独占之类：降级而不是崩
            self.errors += 1
            if self.errors <= 1:
                self.note = f"写手柄失败，已停止尝试：{exc}"
            self.backend = "off"
            self._release_all_quietly()

    def failsafe(self) -> None:
        """断流时回中 + 松开所有键（车还在跑的话，方向自己回正比卡在打死更安全）。"""
        if not self.active:
            return
        try:
            self._apply_stick(0.0)
            self.pad.left_trigger_float(value_float=0.0)
            self.pad.right_trigger_float(value_float=0.0)
            for code in BUTTON_CODES:
                if self.mask & mask_bit(code):
                    self._press(code, False)
            self.mask = 0
            self.pad.update()
        except Exception:
            self.backend = "off"

    def _release_all_quietly(self) -> None:
        try:
            if self.pad is not None:
                self.pad.reset()
        except Exception:
            pass
        self.mask = 0

    def close(self) -> None:
        if self.pad is None:
            return
        try:
            self.pad.reset()           # 回中 + 松键，避免下一个程序拿到一个卡住的手柄
        except Exception:
            pass
        self.pad = None
        self.backend = "off"


def _selftest() -> None:
    """不依赖驱动和真实手柄：用一个假 vgamepad 模块验证映射逻辑。"""
    import sys
    import types

    calls: list[tuple[str, object]] = []

    fake = types.ModuleType("vgamepad")

    class _Btn:
        pass

    for name in BUTTON_ENUM.values():
        setattr(_Btn, name, name)

    class FakePad:
        def press_button(self, button=None):
            calls.append(("press", button))

        def release_button(self, button=None):
            calls.append(("release", button))

        def left_joystick_float(self, x_value_float=0.0, y_value_float=0.0):
            calls.append(("lx", round(x_value_float, 4)))

        def right_joystick_float(self, x_value_float=0.0, y_value_float=0.0):
            calls.append(("rx", round(x_value_float, 4)))

        def left_trigger_float(self, value_float=0.0):
            calls.append(("lt", round(value_float, 4)))

        def right_trigger_float(self, value_float=0.0):
            calls.append(("rt", round(value_float, 4)))

        def update(self):
            calls.append(("update", None))

        def reset(self):
            calls.append(("reset", None))

    fake.XUSB_BUTTON = _Btn
    fake.VX360Gamepad = FakePad
    sys.modules["vgamepad"] = fake

    pad = GamepadOut(enabled=True, invert=False, gain=1.0, stick="lx")
    print("后端：", pad.backend, "|", pad.describe())

    pad.update(0.5, 0b1)          # 半圈 + A
    pad.update(0.5, 0b1)          # 没变化，不应重复按键
    pad.update(0.0, 0b1 | (1 << 6) | (1 << 7))   # 回中 + 加 LT/RT
    pad.update(0.0, 0)            # 全松
    pad.update(0.0, mask_bit(11) | mask_bit(14))  # D-pad 上 + 右
    pad.update(0.0, 0)
    pad.failsafe()
    pad.close()

    presses = [c for c in calls if c[0] == "press"]
    releases = [c for c in calls if c[0] == "release"]
    lx = [c[1] for c in calls if c[0] == "lx"]
    lt = [c[1] for c in calls if c[0] == "lt"]
    print("按键按下：", presses)
    print("按键松开：", releases)
    print("左摇杆 X 序列：", lx)
    print("左扳机序列：", lt)
    print("统计：", pad.stats(), "| errors =", pad.errors)

    assert presses == [("press", "XUSB_GAMEPAD_A"),
                       ("press", "XUSB_GAMEPAD_DPAD_UP"),
                       ("press", "XUSB_GAMEPAD_DPAD_RIGHT")], presses
    assert releases == [("release", "XUSB_GAMEPAD_A"),
                        ("release", "XUSB_GAMEPAD_DPAD_UP"),
                        ("release", "XUSB_GAMEPAD_DPAD_RIGHT")], releases
    assert lx[:3] == [0.5, 0.5, 0.0], lx
    assert lt.count(1.0) == 1 and lt[-1] == 0.0, lt
    assert pad.errors == 0
    print("[ok] 映射逻辑自测通过")


def _real_test() -> int:
    """真机自检：需要一个真实可用的 vgamepad + ViGEmBus。

    跑完去「设置 → 蓝牙和其他设备 → 设备和打印机」里能看到一个 Xbox 360 手柄，
    或者打开 https://hardwaretester.com/gamepad 看左摇杆有没有来回动。
    """
    import time

    pad = GamepadOut(enabled=True, invert=False, gain=1.0, stick="lx")
    print("后端：", pad.backend, "|", pad.describe())
    if not pad.active:
        print("[x] 手柄没连上，先修依赖再试")
        return 1
    try:
        print("左摇杆 X 从 -1 扫到 +1（约 3 秒）…")
        for i in range(21):
            pad.update(-1.0 + i * 0.1, 0)
            time.sleep(0.15)
        print("按 A …")
        pad.update(0.0, 1 << 0)
        time.sleep(0.4)
        print("按 A + LT …")
        pad.update(0.0, (1 << 0) | (1 << 6))
        time.sleep(0.4)
        print("全部松开、回中")
        pad.update(0.0, 0)
        time.sleep(0.2)
    finally:
        pad.close()
    print("[ok]", pad.stats())
    return 0


if __name__ == "__main__":
    import sys as _sys

    if "--real" in _sys.argv:
        raise SystemExit(_real_test())
    _selftest()
