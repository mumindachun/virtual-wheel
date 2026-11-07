// 两个页面共用的设置项，持久化在本地存储（卸载 App 才清）。
import { setLang, axisName, themeName, orientName } from './i18n.js'

export const DEFAULTS = {
	ip: '192.168.1.100',
	port: '8888',
	range: 540, // 角度范围：90..900 之间任意整数（= ±N°，无级调节）
	axis: 3, // 0=X 1=Y 2=Z 3=自动识别
	deadzone: 0.02, // rad/s
	smoothing: 0.3, // 0~0.95，每次采样的一阶平滑
	selfCenter: 0.0, // 1/秒，0 = 关闭
	theme: 'auto', // auto | light | dark
	orientation: 'portrait', // auto | landscape | portrait
	language: 'auto' // auto | zh-Hans | zh-Hant | en
}

export const settings = {
	ip: DEFAULTS.ip,
	port: DEFAULTS.port,
	range: DEFAULTS.range,
	axis: DEFAULTS.axis,
	deadzone: DEFAULTS.deadzone,
	smoothing: DEFAULTS.smoothing,
	selfCenter: DEFAULTS.selfCenter,
	theme: DEFAULTS.theme,
	orientation: DEFAULTS.orientation,
	language: DEFAULTS.language
}

const STORAGE_KEY = 'vw-settings'

// 角度范围：range 存的是「单边」角度，所以 ±90° 就是 range=90（总量程 180°）。
export const RANGE_MIN = 90
export const RANGE_MAX = 900
export const RANGE_PRESETS = [90, 180, 270, 360, 450, 540, 630, 720, 810, 900]

export function clampRange(v) {
	const n = Math.round(Number(v))
	if (isNaN(n)) {
		return DEFAULTS.range
	}
	if (n < RANGE_MIN) {
		return RANGE_MIN
	}
	if (n > RANGE_MAX) {
		return RANGE_MAX
	}
	return n
}

export function loadSettings() {
	try {
		const raw = uni.getStorageSync(STORAGE_KEY)
		if (raw !== null && raw !== undefined && typeof raw === 'string' && raw.length > 0) {
			const saved = JSON.parse(raw)
			if (saved.ip !== undefined) settings.ip = saved.ip
			if (saved.port !== undefined) settings.port = saved.port
			if (saved.range !== undefined) settings.range = clampRange(saved.range)
			if (saved.axis !== undefined) settings.axis = Number(saved.axis)
			if (saved.deadzone !== undefined) settings.deadzone = Number(saved.deadzone)
			if (saved.smoothing !== undefined) settings.smoothing = Number(saved.smoothing)
			if (saved.selfCenter !== undefined) settings.selfCenter = Number(saved.selfCenter)
			if (saved.theme !== undefined) settings.theme = saved.theme
			if (saved.orientation !== undefined) settings.orientation = saved.orientation
			if (saved.language !== undefined) settings.language = saved.language
		}
	} catch (e) {
		// 存储坏了就用默认值，不能因此让页面打不开
	}
	return settings
}

export function saveSettings() {
	try {
		uni.setStorageSync(STORAGE_KEY, JSON.stringify(settings))
	} catch (e) {}
}

export function resetSettings() {
	settings.ip = DEFAULTS.ip
	settings.port = DEFAULTS.port
	settings.range = DEFAULTS.range
	settings.axis = DEFAULTS.axis
	settings.deadzone = DEFAULTS.deadzone
	settings.smoothing = DEFAULTS.smoothing
	settings.selfCenter = DEFAULTS.selfCenter
	settings.theme = DEFAULTS.theme
	settings.orientation = DEFAULTS.orientation
	settings.language = DEFAULTS.language
}

// 运行中用它判断参数有没有被改过（改了就把配置包重新下发给电脑端）
export function configKey() {
	return (
		settings.range +
		'|' +
		settings.axis +
		'|' +
		settings.deadzone +
		'|' +
		settings.smoothing +
		'|' +
		settings.selfCenter
	)
}

export function rangeLabel() {
	return '±' + settings.range + '°'
}

export function axisLabel() {
	return axisName(settings.axis)
}

export function themeLabel() {
	return themeName(settings.theme)
}

export function orientationLabel() {
	return orientName(settings.orientation)
}

// setAppTheme 会让 CSS 的 @media (prefers-color-scheme: dark) 自动切换，颜色不用在 JS 里改
export function applyTheme() {
	try {
		if (typeof uni.setAppTheme === 'function') {
			uni.setAppTheme({ theme: settings.theme })
		}
	} catch (e) {}
}

// 页面 import 时就完成「读设置 + 选定语言」
loadSettings()
setLang(settings.language)
