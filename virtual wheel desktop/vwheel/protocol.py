"""UDP 协议常量与按键表（电脑端与假数据发送器共用）。

样本包 `<ii7dii4d>`（104 字节）、配置包 `<iii3d>`（36 字节），均为小端；
按键位图 bit = 1 << (code - 1)，BUTTON_ENUM 是 code → vgamepad 枚举名（字符串，延迟导入）。
"""

from __future__ import annotations

import struct

TYPE_SAMPLE = 1
TYPE_CONFIG = 2

SAMPLE_FMT = "<ii7dii4d"
SAMPLE_SIZE = struct.calcsize(SAMPLE_FMT)      # 104
CONFIG_FMT = "<iii3d"
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)      # 36

FLAG_RESET = 1        # 手机点了「回正」：角度归零
FLAG_RECALIB = 2      # 手机点了「校准」：重新采零偏

# 按键编号 → 名字，和手机端 pages/index/index.uvue 里的 BUTTONS 一致
BUTTON_CODES = {
    1: "A", 2: "B", 3: "X", 4: "Y",
    5: "LB", 6: "RB", 7: "LT", 8: "RT",
    9: "L3", 10: "L4",
    11: "UP", 12: "DOWN", 13: "LEFT", 14: "RIGHT",
}

# 打印用：D-pad 显示成箭头（其余直接用名字）
BUTTON_LABELS = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→"}

# code → vgamepad 的 XUSB_BUTTON 枚举名；LT/RT 走左右扳机的模拟量，不在表里
BUTTON_ENUM = {
    1: "XUSB_GAMEPAD_A",
    2: "XUSB_GAMEPAD_B",
    3: "XUSB_GAMEPAD_X",
    4: "XUSB_GAMEPAD_Y",
    5: "XUSB_GAMEPAD_LEFT_SHOULDER",
    6: "XUSB_GAMEPAD_RIGHT_SHOULDER",
    9: "XUSB_GAMEPAD_LEFT_THUMB",
    10: "XUSB_GAMEPAD_RIGHT_THUMB",
    11: "XUSB_GAMEPAD_DPAD_UP",
    12: "XUSB_GAMEPAD_DPAD_DOWN",
    13: "XUSB_GAMEPAD_DPAD_LEFT",
    14: "XUSB_GAMEPAD_DPAD_RIGHT",
}


def mask_bit(code: int) -> int:
    """按键号 → 位图里那一位。"""
    return 1 << (code - 1)


def button_label(code: int) -> str:
    """按键号 → 打印用的单个标签（D-pad 用箭头）。"""
    name = BUTTON_CODES[code]
    return BUTTON_LABELS.get(name, name)


def button_list(mask: int) -> list[str]:
    """位图 → 按编号排好序的按键标签列表。"""
    return [button_label(code) for code in sorted(BUTTON_CODES) if mask & mask_bit(code)]


def button_text(mask: int) -> str:
    """位图 → 一行按键文本（`A+LB` / `↑+→`），没按返回 `-`。"""
    names = button_list(mask)
    return "+".join(names) if names else "-"
