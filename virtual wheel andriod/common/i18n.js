// 极简多语言：三份字典 + 一个响应式当前语言。
// 页面用 const ui = computed(() => strings(i18nState.lang))，模板里 ui.xxx，
// 语言一变，computed 重算，界面立刻跟着切换（不用重启页面）。
import { reactive } from 'vue'

export const LANGS = ['auto', 'zh-Hans', 'zh-Hant', 'en']

const MESSAGES = {
	'zh-Hans': {
		lang_auto: '跟随系统',
		lang_zhHans: '简体中文',
		lang_zhHant: '繁體中文',
		lang_en: 'English',

		appTitle: '虚拟方向盘',
		settings: '设置',
		back: '← 返回',
		save: '保存',
		restore: '恢复默认',
		saved: '已保存',
		restored: '已恢复默认值，点「保存」生效',

		start: '开始',
		stop: '停止',
		zero: '回正',
		recalib: '重新校准',
		statusInit: '先到「设置」里填电脑 IP，再点开始',
		statusRun: '正在发送到 {0}:{1} · {2}',
		pressStartFirst: '先点「开始」再按键',
		pressStartTo: '先点「开始」',
		badIp: '电脑 IP 不对，去「设置」里填，例如 192.168.1.100',
		badPort: '端口不对（1-65535），去「设置」里改',
		badIpLong: '电脑 IP 要写成 4 段，例如 192.168.1.100',
		badPortLong: '端口要在 1-65535 之间',
		paramsUpdated: '参数已更新并同步到电脑端',
		webPreview: '浏览器预览没有 UDP 也没有传感器，请运行到 Android 真机',
		stopped: '已停止',
		zeroRequested: '已请求电脑端把角度归零',
		recalibRequested: '已请求重新校准：请把手机保持静止 1 秒',
		metaLine: '{0} 包 · 键 {1}',
		attRef: '姿态参考：{0}',
		axisAutoTip: '轴=自动：开始后把手机当方向盘，慢慢左右各打一次，电脑端识别出旋转轴后就会正常出角度',
		axisWord: '轴',

		secAppearance: '外观',
		secOrientation: '屏幕方向',
		secLanguage: '语言',
		secConnection: '连接',
		secRange: '角度范围',
		secAxis: '转向轴',
		secFilter: '滤波',
		theme_auto: '跟随系统',
		theme_light: '浅色',
		theme_dark: '深色',
		orient_auto: '自动',
		orient_landscape: '横屏',
		orient_portrait: '竖屏',
		axis_0: 'X',
		axis_1: 'Y',
		axis_2: 'Z',
		axis_3: '自动',
		labelIp: '电脑 IP',
		labelPort: '端口',
		labelDeadzone: '死区',
		labelSmoothing: '平滑',
		labelSelfCenter: '自动回正',
		noteTheme: '深色模式跟随系统的开关也能用；这里手动指定优先。',
		noteOrientation: '横屏时主界面是「左边扳机、中间控制、右边 ABXY」。自动 = 跟着重力转。保存后回主界面生效。',
		noteLanguage: '「跟随系统」按手机语言自动选；切换后立即生效。',
		noteConnection: '电脑端 main.py 启动时会打印本机局域网 IP，照着填。',
		noteRange: '单边 90°~900° 之间任意整数（无级）。90 就是「±90°」（总量程 180°），越大越接近真车的多圈方向盘。手机转到满量程时电脑端输出到 ±32767。',
		rangeTotal: '当前总量程 {0}°（±{1}° × 2）',
		noteAxis: '「自动」不假设手机怎么贴：开始后慢慢左右各打一次，电脑端自动算出旋转轴，斜贴也准。',
		noteFilter: '死区：小于这个角速度当没动，防漂移。平滑：越大越顺但越迟滞。自动回正：0 = 关。',
		unitRate: 'rad/s',
		unitSmooth: '0~0.95',
		unitPerSec: '1/秒'
	},
	'zh-Hant': {
		lang_auto: '跟隨系統',
		lang_zhHans: '简体中文',
		lang_zhHant: '繁體中文',
		lang_en: 'English',

		appTitle: '虛擬方向盤',
		settings: '設定',
		back: '← 返回',
		save: '儲存',
		restore: '恢復預設',
		saved: '已儲存',
		restored: '已恢復預設值，點「儲存」生效',

		start: '開始',
		stop: '停止',
		zero: '回正',
		recalib: '重新校準',
		statusInit: '先到「設定」裡填電腦 IP，再點開始',
		statusRun: '正在傳送到 {0}:{1} · {2}',
		pressStartFirst: '先點「開始」再按鍵',
		pressStartTo: '先點「開始」',
		badIp: '電腦 IP 不對，去「設定」裡填，例如 192.168.1.100',
		badPort: '連接埠不對（1-65535），去「設定」裡改',
		badIpLong: '電腦 IP 要寫成 4 段，例如 192.168.1.100',
		badPortLong: '連接埠要在 1-65535 之間',
		paramsUpdated: '參數已更新並同步到電腦端',
		webPreview: '瀏覽器預覽沒有 UDP 也沒有感測器，請執行到 Android 真機',
		stopped: '已停止',
		zeroRequested: '已請求電腦端把角度歸零',
		recalibRequested: '已請求重新校準：請把手機保持靜止 1 秒',
		metaLine: '{0} 包 · 鍵 {1}',
		attRef: '姿態參考：{0}',
		axisAutoTip: '軸=自動：開始後把手機當方向盤，慢慢左右各打一次，電腦端識別出旋轉軸後就會正常出角度',
		axisWord: '軸',

		secAppearance: '外觀',
		secOrientation: '螢幕方向',
		secLanguage: '語言',
		secConnection: '連線',
		secRange: '角度範圍',
		secAxis: '轉向軸',
		secFilter: '濾波',
		theme_auto: '跟隨系統',
		theme_light: '淺色',
		theme_dark: '深色',
		orient_auto: '自動',
		orient_landscape: '橫向',
		orient_portrait: '直向',
		axis_0: 'X',
		axis_1: 'Y',
		axis_2: 'Z',
		axis_3: '自動',
		labelIp: '電腦 IP',
		labelPort: '連接埠',
		labelDeadzone: '死區',
		labelSmoothing: '平滑',
		labelSelfCenter: '自動回正',
		noteTheme: '深色模式跟隨系統的開關也能用；這裡手動指定優先。',
		noteOrientation: '橫向時主畫面是「左邊扳機、中間控制、右邊 ABXY」。自動 = 跟著重力轉。儲存後回主畫面生效。',
		noteLanguage: '「跟隨系統」依手機語言自動選；切換後立即生效。',
		noteConnection: '電腦端 main.py 啟動時會印出本機區域網路 IP，照著填。',
		noteRange: '單邊 90°~900° 之間任意整數（無級）。90 就是「±90°」（總量程 180°），越大越接近真車的多圈方向盤。手機轉到滿量程時電腦端輸出到 ±32767。',
		rangeTotal: '目前總量程 {0}°（±{1}° × 2）',
		noteAxis: '「自動」不假設手機怎麼貼：開始後慢慢左右各打一次，電腦端自動算出旋轉軸，斜貼也準。',
		noteFilter: '死區：小於這個角速度當沒動，防漂移。平滑：越大越順但越遲滯。自動回正：0 = 關。',
		unitRate: 'rad/s',
		unitSmooth: '0~0.95',
		unitPerSec: '1/秒'
	},
	en: {
		lang_auto: 'System',
		lang_zhHans: '简体中文',
		lang_zhHant: '繁體中文',
		lang_en: 'English',

		appTitle: 'Virtual Wheel',
		settings: 'Settings',
		back: '← Back',
		save: 'Save',
		restore: 'Defaults',
		saved: 'Saved',
		restored: 'Defaults restored, tap Save to apply',

		start: 'Start',
		stop: 'Stop',
		zero: 'Center',
		recalib: 'Recalibrate',
		statusInit: 'Set the PC IP in Settings, then tap Start',
		statusRun: 'Sending to {0}:{1} · {2}',
		pressStartFirst: 'Tap Start before pressing buttons',
		pressStartTo: 'Tap Start first',
		badIp: 'Invalid PC IP, set it in Settings (e.g. 192.168.1.100)',
		badPort: 'Invalid port (1-65535), fix it in Settings',
		badIpLong: 'IP must have 4 parts, e.g. 192.168.1.100',
		badPortLong: 'Port must be 1-65535',
		paramsUpdated: 'Settings synced to the PC',
		webPreview: 'Web preview has no UDP and no sensors — run on a real Android device',
		stopped: 'Stopped',
		zeroRequested: 'Asked the PC to zero the angle',
		recalibRequested: 'Recalibrating: keep the phone still for 1 s',
		metaLine: '{0} pkts · keys {1}',
		attRef: 'Attitude: {0}',
		axisAutoTip: 'Axis=Auto: after Start, turn slowly left and right once so the PC can find the rotation axis',
		axisWord: 'axis',

		secAppearance: 'Appearance',
		secOrientation: 'Screen orientation',
		secLanguage: 'Language',
		secConnection: 'Connection',
		secRange: 'Angle range',
		secAxis: 'Steering axis',
		secFilter: 'Filter',
		theme_auto: 'System',
		theme_light: 'Light',
		theme_dark: 'Dark',
		orient_auto: 'Auto',
		orient_landscape: 'Landscape',
		orient_portrait: 'Portrait',
		axis_0: 'X',
		axis_1: 'Y',
		axis_2: 'Z',
		axis_3: 'Auto',
		labelIp: 'PC IP',
		labelPort: 'Port',
		labelDeadzone: 'Deadzone',
		labelSmoothing: 'Smoothing',
		labelSelfCenter: 'Self-center',
		noteTheme: 'Dark mode also follows the system switch; picking one here wins.',
		noteOrientation: 'Landscape puts triggers left, controls center, ABXY right. Auto follows gravity. Applies after saving.',
		noteLanguage: 'Auto follows the phone language; switching applies immediately.',
		noteConnection: 'main.py prints the local IP on startup — copy it here.',
		noteRange: 'Any integer from 90° to 900° (stepless). 90 means "±90°" (180° total); higher values feel more like a real multi-turn wheel. Full scale maps to ±32767 on the PC.',
		rangeTotal: 'Current full range {0}° (±{1}° × 2)',
		noteAxis: 'Auto assumes nothing about how the phone is mounted: turn left and right once after Start.',
		noteFilter: 'Deadzone: below this rate counts as still. Smoothing: higher = smoother but laggier. Self-center: 0 = off.',
		unitRate: 'rad/s',
		unitSmooth: '0~0.95',
		unitPerSec: '1/s'
	}
}

export const i18nState = reactive({ lang: 'zh-Hans' })

function normalize(lang) {
	const s = String(lang).replace('_', '-').toLowerCase()
	if (s.indexOf('zh') === 0) {
		return s.indexOf('hant') >= 0 || s.indexOf('tw') >= 0 || s.indexOf('hk') >= 0 || s.indexOf('mo') >= 0
			? 'zh-Hant'
			: 'zh-Hans'
	}
	return 'en'
}

function detect() {
	try {
		const info = uni.getAppBaseInfo()
		const lang = String(info.language)
		if (lang !== '') {
			return normalize(lang)
		}
	} catch (e) {}
	try {
		const locale = String(uni.getLocale())
		if (locale !== '') {
			return normalize(locale)
		}
	} catch (e) {}
	return 'zh-Hans'
}

export function resolveLang(pref) {
	const p = String(pref)
	if (p === 'auto' || p === '') {
		return detect()
	}
	return normalize(p)
}

export function setLang(pref) {
	i18nState.lang = resolveLang(pref)
	return i18nState.lang
}

export function strings(lang) {
	const dict = MESSAGES[lang]
	return dict !== undefined ? dict : MESSAGES['zh-Hans']
}

// t('key', a, b) —— 占位符写 {0} {1}
export function t(key) {
	const dict = strings(i18nState.lang)
	let s = dict[key]
	if (s === undefined) {
		s = MESSAGES['zh-Hans'][key]
	}
	if (s === undefined) {
		return String(key)
	}
	for (let i = 1; i < arguments.length; i = i + 1) {
		s = s.replace('{' + (i - 1) + '}', String(arguments[i]))
	}
	return s
}

export function themeName(pref) {
	return t('theme_' + String(pref))
}

export function orientName(pref) {
	return t('orient_' + String(pref))
}

export function axisName(axis) {
	return t('axis_' + String(axis))
}

export function langName(pref) {
	const key = String(pref) === 'zh-Hans' ? 'lang_zhHans' : String(pref) === 'zh-Hant' ? 'lang_zhHant' : String(pref) === 'en' ? 'lang_en' : 'lang_auto'
	return t(key)
}
