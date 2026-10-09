/** A hint for labels/defaults; opening a native link uses the user's current browser. */
export function detectBrowser(ua: string): {name: string; installedHint: string} {
  if (/Edg\//.test(ua)) return {name: 'Microsoft Edge', installedHint: 'edge'};
  if (/OPR\//.test(ua)) return {name: 'Opera', installedHint: 'opera'};
  if (/Firefox\//.test(ua)) return {name: 'Firefox', installedHint: 'firefox'};
  if (/Electron\//.test(ua)) return {name: '', installedHint: ''};
  if (/Chrome\//.test(ua)) return {name: 'Chrome', installedHint: 'chrome'};
  if (/Safari\//.test(ua)) return {name: 'Safari', installedHint: 'safari'};
  return {name: '', installedHint: ''};
}
