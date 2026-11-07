"""虚拟方向盘 · 电脑端入口。

    python main.py                     # 监听 0.0.0.0:8888，默认 ±540°，写虚拟手柄
    python main.py --no-gamepad        # 只打印，不写手柄
    python main.py --help              # 全部参数
"""

from __future__ import annotations

from vwheel.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
