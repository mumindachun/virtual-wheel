# 手机端 —— 陀螺仪 + 加速度计 + Xbox 按键 → UDP

采集传感器和按键，按协议打成 UDP 包直接发到电脑。**所有滤波、积分、映射都在电脑端做**，
手机端只负责采集 + 传输，这样调参数不用反复编译手机端。

## 目录里都有什么

```
pages/index/index.uvue                        主界面：Xbox 布局按键 + 中间的开始/停止/回正/校准，横竖屏自适应
pages/settings/settings.uvue                  设置页：外观/语言/屏幕方向、IP/端口、角度范围、转向轴、死区/平滑/自动回正
common/settings.js                            两个页面共用的设置对象 + 本地存储读写（含 theme / orientation）
uni_modules/vw-udp/package.json               插件描述（id: vw-udp）
uni_modules/vw-udp/utssdk/app-android/index.uts Android 端 UDP 发送器（java.net.DatagramSocket）
uni_modules/vw-udp/utssdk/web/index.uts       Web 端空实现，只为让浏览器预览能编译
uni_modules/vw-screen/package.json            插件描述（id: vw-screen）
uni_modules/vw-screen/utssdk/app-android/index.uts 切横竖屏（Activity.setRequestedOrientation）
uni_modules/vw-screen/utssdk/web/index.uts    Web 端空实现（浏览器没法锁方向）
pages.json                                    注册了 pages/index/index 和 pages/settings/settings
```

三个必须知道的约束（不是写法偏好，是 uni-app x 的硬限制）：

1. **蒸汽模式（vapor）只支持组合式 API**，不支持 `export default { data(){}, methods:{} }`，
   所以页面写成了 `<script setup>`。
2. **蒸汽模式下 uvue 页面里不能直接调原生 API**（`utsAndroid` 也不可用），
   `java.net` 的 socket 必须挪到 uts 插件里，页面只调用插件导出的函数。
3. **uts 代码默认跑在 main（UI）线程**，直接 `send()` 会抛 `NetworkOnMainThreadException`，
   所以插件里起了一个常驻后台线程，主线程只把最新样本丢给它（`Semaphore` 唤醒）。

还有一条隐藏的坑：**uts 里喂给原生 API 的数字必须是 `Int/Double`**，不能直接给 `number`
（`number` 在 Kotlin 里是抽象类 `Number`，官方文档写了「入参要求传入 Int，那么传入 number 会报错」）。
插件里所有包内字段和 Java 调用都用 `Int/Double`，只在导出的函数签名上用 `number` 并在边界转换。

## 怎么跑

1. 用 **HBuilderX 5.21 或更新的版本**（蒸汽模式的要求，`manifest.json` 里 `vapor: true` 已经开了）打开本目录。
2. 手机（Android 6.0+，要有陀螺仪）用 USB 连电脑，HBuilderX 菜单 **运行 → 运行到手机或模拟器**。
   第一次运行按提示授权即可；传感器是系统能力，不需要额外申请权限，网络权限标准基座里已经带了。
3. 电脑端先跑起来：`python main.py`（在 `virtual wheel desktop` 目录里），它会打印本机局域网 IP。
4. 手机进 **⚙ 设置**，填电脑 IP / 端口，设角度范围（单边 90°~900° 无级：90 就是 ±90°，540 就是 ±540°）和转向轴，保存。
   转向轴默认「自动」：不假设手机怎么贴，开始后把手机当方向盘**慢慢左右各打一次**，
   电脑端会算出旋转轴（打印 `✓ 旋转轴已锁定 n=(...)`），之后倾斜安装也准。
   只想固定某一轴就在设置里选 X / Y / Z。
5. 回主界面点 **开始**。电脑端开始每 0.1 秒刷一行；按住 ABXY 等按键，电脑端会打印 `↓ 按下 A`。

> 模拟器没有陀螺仪，必须用真机。
> 页面必须保持在前台：切后台 / 锁屏后系统会停掉陀螺仪回调，电脑端会显示「已断流」。

## 主界面的按键

按 Xbox 习惯排：**左边一列 LT / LB / L3，右边一列 RT / RB / L4，靠中间是十字方向键，右侧是 Y-X-B-A 菱形**，
开始/停止、回正、重新校准都收在正中间（不跟手柄按键混在一起）。共 14 个按键，对应 Xbox 手柄：

| 界面 | 手柄 | 说明 |
|------|------|------|
| X / Y / A / B | 同名 | 右下菱形，Y 上、X 左、B 右、A 下 |
| LB / RB | 同名 | 肩键 |
| LT / RT | 同名 | 扳机（现在按位图当按钮发；以后要模拟量可以改成读按压力度） |
| L3 | 左摇杆按下 | 左列最下 |
| L4 | 右摇杆按下 | 右列最下，复用位图的 bit9 |
| ↑ ↓ ← → | 十字方向键 | 方向键块，`▲◀▶▼` 四个按钮，一一对应 |

`touchstart` 置位、`touchend/touchcancel` 清位，位图随每个样本包发出去，所以丢一包也不会卡住状态。

「回正」= 让电脑端把当前角度当 0；「重新校准」= 重新采集 1 秒零偏（此时手机要静止）。

## 界面：横竖屏 + 深色模式

- **没有系统导航栏**：`pages.json` 里两个页面都设了 `"navigationStyle": "custom"`，
  所以顶上那条「虚拟方向盘」标题栏（由系统绘制、高度不可调）没有了，页面自己画顶栏。
  代价是内容会顶到屏幕最上面，所以两个页面都用 `uni.getWindowInfo().statusBarHeight`
  补了一段 padding，避免被时间/电量挡到。设置页因此自己画了「← 返回」按钮（在设置页头部）。
- **横竖屏**：顶栏右侧那个按钮循环切换「自动 → 横屏 → 竖屏」（也可以在设置页里选），
  保存后立刻生效，不用重开 App。横屏是 `左扳机 | 中间控制 | ABXY | 右扳机` 一行排开；
  竖屏自动变上下排布，两侧按键变成一行三个。实现方式见 `uni_modules/vw-screen`：
  蒸汽模式下页面不能调原生 API，所以 `Activity.setRequestedOrientation` 放在 uts 插件里
  （`6` = 横屏、`7` = 竖屏、`10` = 跟随重力）。
- **深色模式**：跟系统走（`manifest.json` 里 `app.defaultAppTheme: "auto"`），
  也能在顶栏按钮 / 设置页里手动选「跟随系统 / 浅色 / 深色」，运行时用 `uni.setAppTheme` 切换。
  颜色全部写在 CSS 的 `@media (prefers-color-scheme: dark)` 里，浅色是基础样式、深色只做覆盖，
  所以即使某个平台不认这个媒体查询，界面也不会变成看不见的黑字黑底。

## 多语言

界面文案集中在 `common/i18n.js`，有三份字典：**简体中文（`zh-Hans`）、繁体中文（`zh-Hant`）、English（`en`）**。

- **切换入口**：设置页 → 语言（四行：跟随系统 / 简体中文 / 繁體中文 / English）。点一下就预览，
  点「保存」才写进本地存储；主界面顶栏不占位置，所以没放语言按钮。
- **跟随系统**：`auto` 时读 `uni.getAppBaseInfo().language`（拿不到再退 `uni.getLocale()`），
  `zh-CN`/`zh-TW`/`en-US` 这类带地区后缀的会自动归一。
- **代码里怎么用**：页面里 `const ui = computed(() => strings(i18nState.lang))`，
  然后模板直接 `{{ ui.save }}`；带参数的用 `t('metaLine', sent, mask)`（`{0}`/`{1}` 占位）。
  `i18nState` 是 `reactive` 的，改语言后所有绑定立刻重算，不用重启页面。
- **加一门语言**：在 `MESSAGES` 里加一份字典（key 保持一致）、在 `LANGS` 里加一项，设置页的列表会自动多一行。

## 发包格式（和电脑端 `vwheel/protocol.py` 一致，小端）

**样本包 104 字节** `<ii7dii4d>`：`type=1, seq, gx,gy,gz, ax,ay,az, t, btnMask, flags, qx,qy,qz,qw`

- `gx/gy/gz`：角速度，rad/s，静止时接近 0。
- `ax/ay/az`：加速度，单位 g，手机平放不动时 `az ≈ 1.0`。
- `t`：**采样时刻**的 Unix epoch 毫秒（插件里 `System.currentTimeMillis()`），电脑端用它算 `dt`。
- `btnMask`：按键位图，`bit(n) = 1 << (code-1)`，A=1 … L4=10。
- `flags`：bit0 = 角度归零，bit1 = 重新校准；插件会连发 3 包防止丢包。
- `qx/qy/qz/qw`：姿态四元数，来自 Android 的 `TYPE_ROTATION_VECTOR`（系统融合姿态，`(x,y,z,w)` 格式）。
  插件在 `openUdp` 时注册传感器、`closeUdp` 时注销；拿不到数据时发全 0，电脑端看到全 0 就自动退化成纯陀螺积分。
  页面状态卡里有一行「姿态参考：ok / 等待数据… / 这台设备没有旋转向量传感器」。

**配置包 36 字节** `<iii3d>`：`type=2, rangeDeg, axis, deadzone, smoothing, selfCenter`
（`rangeDeg` 是单边角度，90..900；`90` = ±90°，`900` = ±900°，中间任意整数，电脑端会夹到合法区间）
—— 开始发送时发一次，之后设置页每改一次就重发一次（运行中改，电脑端立即生效）。

插件内部直接注册传感器（请求 5000µs ≈ 200Hz，设备给不了会自动降频），由陀螺仪回调驱动发包；加速度计的值取“最近一次”的那个，最多旧 5ms。
两个传感器回调本来就不保证同频同步，这样打包能保证时间戳和主数据严格对齐。

## 收不到 / 连不上？

- 手机页面上「已发送」不涨 → 陀螺仪没起来，看页面上的红字提示（有的机型角速度传感器被省电策略限制）。
- 页面提示「加速度计不可用」但「已发送」在涨 → 只有陀螺仪在发，`ax/ay/az` 会是 0，不影响链路验证。
- 「已发送」在涨但电脑端没反应 → 网络问题：确认同一 Wi-Fi、IP 没填错、Windows 防火墙放行（详见电脑端 README）。
- 按键按了电脑端没反应 → 先确认电脑端 `pkt/s` 在 200 左右（按键只跟着样本包走）。
- 改了 `vw-udp` 插件代码后，需要重新运行（改动 uts 会触发重新编译，标准基座就够，不用做自定义基座）。

## 已知限制（demo 范围内故意没做）

- 时间戳是手机端 `Date.now()`（系统时钟），没有和电脑端做时钟对齐，只适合算间隔 / 做积分。
- 按键只有数字量，没有扳机行程（LT/RT 的模拟量要另开字段）。
- 转向轴选「自动」时，开始后那一次左右打方向被用来识别旋转轴，识别完成时角度会清零；
  识别期间（电脑端显示「识别旋转轴…」）电脑端不出角度，这是设计如此，不是坏了。
- 没有重连、没有心跳、没有加密，纯局域网明文。
- 页面没有常亮屏幕，也没有处理切后台（切后台就断流）。
