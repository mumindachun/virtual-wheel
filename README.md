# 虚拟方向盘

以 Android 设备陀螺仪作为输入，经局域网 UDP 传输至 PC 端完成滤波、积分与映射，最终写入虚拟 Xbox 360 手柄（vgamepad + ViGEmBus）：

**移动端传感器 / 按键 → UDP → PC 端信号处理 → 虚拟手柄 → 游戏**

移动端仅负责采集与发送，信号处理及参数配置集中在 PC 端，调整参数无需重新编译移动端应用。界面支持横竖屏、深色模式及简中/繁中/英文。

## 运行方式

### PC 端（Windows / Python 3）

```bash
cd "virtual wheel desktop"
pip install -r requirements.txt
python main.py
```

启动横幅输出本机局域网 IP，默认监听 UDP `8888`。虚拟手柄输出依赖 [ViGEmBus 驱动](https://github.com/nefarius/ViGEmBus/releases)；未安装时仍可接收数据、输出状态并执行自检（亦可显式指定 `--no-gamepad`）。

### 移动端（Android 真机）

使用 HBuilderX 打开 `virtual wheel andriod` 并运行至设备；模拟器不提供陀螺仪。在设置页填写 PC 端 IP 与端口并保存，返回主界面启动发送。两端需处于同一局域网，应用须保持前台运行，切至后台将中断数据流。

启动后前 1 秒用于零偏校准，期间保持设备静止。转向轴默认为「自动」：随后缓慢左右各转动一次，待 PC 端输出 `[ok] 旋转轴已锁定` 后方输出角度，锁定时刻角度归零。如需跳过该步骤，可在设置页指定 X / Y / Z 固定轴。

### 离线自检

无需移动端设备时，可在另一终端运行 `python tools/simulate.py` 发送仿真数据；或使用 `python tools/check_freeaxis.py` 自动启停两端并执行 20 秒联调。

PC 端默认每 0.1 秒输出一行状态，`pkt/s` 稳定且角度随设备转动即表示链路正常：

```
[    3.0s]  49.8pkt/s 丢包=0   ±540° ----------#----------  角度=  +57.3°  值= +3477  键=-
```

## 输出映射

| 输入项 | 虚拟手柄 |
|---|---|
| 转向角（±540° → 值 ±32767） | 左摇杆 X（`--stick` 可切换轴） |
| A B X Y / LB RB / L3 L4 / ↑↓←→ | 对应按键 |
| LT RT | 左/右扳机（仅开关量 0 / 1） |

角度量程以**单边**计，可在设置页于 90~900 范围内连续配置（`90` 表示 ±90°），数值越小灵敏度越高。按键以状态位图随每个样本包发送，单个包丢失不会造成状态滞留。手柄每收到一个样本包更新一次；断流超过 1 秒自动回中并释放全部按键，进程退出时执行 reset。

## 信号处理链路

```
gyro → 转轴投影 → 零偏补偿 → 死区 → 一阶低通 → 积分 → 限幅 → ±32767
```

- `dt` 取自样本包内的毫秒时间戳，两端无需时钟同步；断流期间不累加时间。
- **旋转轴识别**：设备倾斜安装时，PC 端由角速度样本协方差的主方向（PCA）估计转轴后投影，避免仅取单一机身轴造成的角度损失。
- **漂移抑制**：静止零偏重估（ZUPT）与姿态四元数慢修正（时间常数约 20 秒）并用。转速高于 15°/s 时暂停姿态修正，以规避系统融合姿态 50~150ms 延迟；磁环境干扰显著时指定 `--no-att`，仅保留 ZUPT。

## 命令行参数

```bash
python main.py --axis auto          # 启用旋转轴自动识别
python main.py --range 360          # 单边量程 ±360°
python main.py --invert             # 反转输出方向
python main.py --gain 1.06          # 补偿 6% 的读数偏低（仅作用于手柄输出）
python main.py --raw                # 输出原始三轴角速度与轴外比，用于量程诊断
python main.py --no-att             # 停用姿态慢修正；--no-zupt 停用静止零偏重估
python main.py --interval 0.01      # 缩短状态输出间隔
```

移动端设置页下发的配置会实时覆盖命令行参数。完整列表见 `python main.py --help`。

## 通信协议

采用小端字节序，两端格式须保持一致。

- **样本包 104 字节** `<ii7dii4d>`：`type=1, seq, gx,gy,gz, ax,ay,az, t, btnMask, flags, qx,qy,qz,qw`。角速度单位 rad/s，加速度单位 g；`t` 为移动端系统时钟毫秒，仅用于计算 `dt`；`flags` bit0=角度归零、bit1=重新校准；四元数全 0 表示无姿态数据。
- **配置包 36 字节** `<iii3d>`：`type=2, rangeDeg, axis(0=X 1=Y 2=Z 3=自动), deadzone, smoothing, selfCenter`。发送启动时下发一次，配置变更时重发。
- **按键位** `1 << (code-1)`，code 1~14 依次为 `A B X Y LB RB LT RT L3 L4 ↑ ↓ ← →`。

## 故障排查

| 现象 | 处置 |
|---|---|
| 无数据到达 | 确认两端处于同一网段、IP 与端口一致，并在 Windows 防火墙放行 python / UDP 8888 |
| 角度系统性偏小 | 指定 `--raw` 读取轴外比：>0.3 表明转轴未对准，改用自动识别；双向均匀偏小多为陀螺标度误差或设备位移，以 `--gain` 的倒数补偿 |
| 静止后角度持续衰减 | 检查设置页「自动回正」是否为 0 |
| 输出 `[!] 姿态与积分相差 …°` | 磁环境干扰，指定 `--no-att` |

## 目录结构

| 路径 | 内容 |
|---|---|
| `virtual wheel andriod/` | uni-app x 移动端：`pages/` 界面与设置、`uni_modules/vw-udp` 传感器采集与 UDP、`vw-screen` 屏幕方向控制 |
| `virtual wheel desktop/` | PC 端：`main.py` 入口、`vwheel/` 协议与算法与手柄与命令行、`tools/` 仿真数据与联调脚本 |

各端实现细节分别参见 [PC 端 README](<virtual wheel desktop/README.md>) 与 [移动端 README](<virtual wheel andriod/README.md>)。

## 已知限制

扳机仅支持开关量，不具备按压力度；无力回馈；链路为局域网明文，未实现重连与加密；应用切至后台即中断数据流；时间戳仅用于计算采样间隔，未做两端时钟对齐。
