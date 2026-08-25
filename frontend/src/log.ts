// 前端运行时日志：捕获浏览器错误，经 /__honeylog 上报，由后端 Vite 插件落盘到 frontend/log/{date}.log.
// 浏览器沙箱无法直接写容器文件，只能经网络上报（sendBeacon 不阻塞页面）。
function report(payload: unknown) {
  try {
    const line = typeof payload === 'string' ? payload : JSON.stringify(payload);
    navigator.sendBeacon('/__honeylog', line.slice(0, 2000));
  } catch {
    /* 上报失败无需处理 */
  }
}

export function initClientLog() {
  // 捕获 console.error（保留原输出）
  const origError = console.error;
  console.error = (...args: unknown[]) => {
    origError.apply(console, args);
    try {
      report({ level: 'console.error', message: args.map(String).join(' ').slice(0, 2000) });
    } catch {
      /* ignore */
    }
  };

  window.addEventListener('error', (e) => {
    report({ level: 'window.onerror', message: (e.message || String(e.error || '')).slice(0, 2000) });
  });

  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason as any;
    report({ level: 'unhandledrejection', message: String(r?.message || r || '').slice(0, 2000) });
  });
}

initClientLog();