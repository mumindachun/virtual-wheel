# Virtual Steering Wheel

<p align="center">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

Uses an Android device's gyroscope as the input source: sensor data is sent over local UDP to a PC, where filtering, integration and mapping are performed before the result is written to a virtual Xbox 360 controller (vgamepad + ViGEmBus).

**Mobile sensors / buttons → UDP → PC-side signal processing → virtual gamepad → game**

The mobile application handles acquisition and transmission only; signal processing and parameter configuration are centralized on the PC, so tuning parameters does not require rebuilding the mobile app. The UI supports portrait/landscape, dark mode, and Simplified Chinese / Traditional Chinese / English.

## Getting Started

### PC (Windows, Python 3)

```bash
cd "virtual wheel desktop"
pip install -r requirements.txt
python main.py
```

The startup banner prints the host's LAN IP address; UDP port `8888` is used by default. Virtual gamepad output requires the [ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases). Without it, the PC side can still receive data, print status and run self-tests (or disable output explicitly with `--no-gamepad`).

### Mobile (Android device)

Open `virtual wheel andriod` in HBuilderX and run it on a physical device; emulators do not provide a gyroscope. Enter the PC's IP address and port in Settings, save, then start transmission from the main screen. Both ends must be on the same LAN, and the app must remain in the foreground — backgrounding it interrupts the data stream.

The first second after startup is used for bias calibration; keep the device stationary. The steering axis defaults to `Auto`: slowly turn left and right once, and angles are reported only after the PC prints `[ok] 旋转轴已锁定` (axis locked); the angle is zeroed at that moment. To skip this step, select a fixed X / Y / Z axis in Settings.

### Offline Verification

Without a mobile device, run `python tools/simulate.py` in a second terminal to send simulated data, or `python tools/check_freeaxis.py` to start and stop both ends automatically for a 20-second integration check.

By default the PC prints one status line every 0.1 s. A stable `pkt/s` and an angle that follows the device indicate a working link:

```
[    3.0s]  49.8pkt/s 丢包=0   ±540° ----------#----------  角度=  +57.3°  值= +3477  键=-
```

## Output Mapping

| Input | Virtual gamepad |
|---|---|
| Steering angle (±540° → value ±32767) | Left stick X (`--stick` selects another axis) |
| A B X Y / LB RB / L3 L4 / ↑↓←→ | Corresponding buttons |
| LT RT | Left/right triggers (digital 0 / 1 only) |

The angle range is specified **per side** and can be set continuously from 90 to 900 in Settings (`90` means ±90°); smaller values yield higher sensitivity. Buttons are transmitted as a state bitmap in every sample packet, so a single lost packet does not leave a key stuck. The gamepad is updated once per received sample packet; if the stream is interrupted for more than 1 s, the steering returns to center and all buttons are released. A reset is performed on exit.

## Signal Processing

```
gyro → axis projection → bias compensation → deadzone → first-order low-pass → integration → clamping → ±32767
```

- `dt` is derived from the millisecond timestamp in each sample packet; no clock synchronization between the two ends is required. Stream gaps are not integrated.
- **Axis estimation**: when the device is mounted at an angle, the PC estimates the rotation axis from the principal direction (PCA) of the angular-velocity samples before projection, avoiding the angle loss caused by reading a single body axis.
- **Drift suppression**: zero-velocity bias re-estimation (ZUPT) combined with slow attitude correction from the uploaded quaternion (time constant ≈ 20 s). Correction is suspended above 15°/s because the system-fused orientation has a 50–150 ms latency. In environments with significant magnetic interference, specify `--no-att` to retain ZUPT only.

## Command-Line Options

```bash
python main.py --axis auto          # enable automatic axis estimation
python main.py --range 360          # per-side range ±360°
python main.py --invert             # invert the output direction
python main.py --gain 1.06          # compensate a 6% low reading (gamepad output only)
python main.py --raw                # print raw 3-axis rates and the off-axis ratio for diagnostics
python main.py --no-att             # disable attitude correction; --no-zupt disables ZUPT
python main.py --interval 0.01      # shorten the status print interval
```

Configuration sent from the mobile Settings page overrides command-line options at runtime. See `python main.py --help` for the complete list.

## Communication Protocol

Little-endian byte order; both ends must use the same layout.

- **Sample packet, 104 bytes** `<ii7dii4d>`: `type=1, seq, gx,gy,gz, ax,ay,az, t, btnMask, flags, qx,qy,qz,qw`. Angular velocity is in rad/s and acceleration in g; `t` is the mobile system clock in milliseconds and is used only to compute `dt`; `flags` bit0 = zero the angle, bit1 = restart calibration; an all-zero quaternion indicates that attitude data is unavailable.
- **Config packet, 36 bytes** `<iii3d>`: `type=2, rangeDeg, axis(0=X 1=Y 2=Z 3=Auto), deadzone, smoothing, selfCenter`. Sent once when transmission starts and resent whenever settings change.
- **Button bit** `1 << (code-1)`, codes 1–14: `A B X Y LB RB LT RT L3 L4 ↑ ↓ ← →`.

## Troubleshooting

| Symptom | Action |
|---|---|
| No packets received | Verify both ends are on the same subnet, the IP and port match, and Windows Firewall allows python / UDP 8888 |
| Angle consistently reads low | Use `--raw` to inspect the off-axis ratio: >0.3 indicates a misaligned axis — switch to Auto. A uniform bias in both directions is typically gyro scale error or device slip; compensate with the reciprocal via `--gain` |
| Angle decays while stationary | Check that "Auto Center" is set to 0 in Settings |
| `[!] 姿态与积分相差 …°` is printed | Magnetic interference; specify `--no-att` |

## Project Structure

| Path | Contents |
|---|---|
| `virtual wheel andriod/` | uni-app x mobile app: `pages/` UI and settings, `uni_modules/vw-udp` sensor acquisition and UDP, `vw-screen` orientation control |
| `virtual wheel desktop/` | PC side: `main.py` entry point, `vwheel/` protocol / processing / gamepad / CLI, `tools/` simulated data and integration scripts |

Per-component details: [PC README](virtual%20wheel%20desktop/README.md) and [Mobile README](virtual%20wheel%20andriod/README.md).

## Known Limitations

Triggers are digital only, with no pressure sensitivity; no force feedback; plaintext LAN traffic without reconnect or encryption; backgrounding the app interrupts the stream; timestamps are used only for sample intervals, with no clock alignment between the two ends.
