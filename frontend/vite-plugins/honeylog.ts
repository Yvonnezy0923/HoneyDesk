// Vite 插件：前端日志按天落盘 → frontend/log/{date}.log，保留最近 10 天，超期 gzip 压缩归档.
// 运行于 Node 侧（dev server）。记录：web 请求、vite/HMR 事件、浏览器上报的运行错误.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import type { Plugin } from 'vite';

const KEEP_DAYS = 10;
const LOG_DIR = path.resolve(process.cwd(), 'log');

function localDay(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function writeLine(day: string, line: string) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(path.join(LOG_DIR, `${day}.log`), line + '\n');
  } catch {
    /* 日志失败不阻断服务 */
  }
}

function pack(full: string) {
  const gz = full + '.gz';
  try {
    fs.writeFileSync(gz, zlib.gzipSync(fs.readFileSync(full)));
    fs.unlinkSync(full);
  } catch {
    /* 打包失败保留明文 */
  }
}

function maintain() {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - KEEP_DAYS);
  let files: string[] = [];
  try {
    files = fs.readdirSync(LOG_DIR);
  } catch {
    return;
  }
  for (const name of files) {
    if (!name.endsWith('.log')) continue;
    const day = name.slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
    const dt = new Date(`${day}T00:00:00`);
    if (dt < cutoff) pack(path.join(LOG_DIR, name));
  }
}

// 惰性维护：一旦跨天，就先归档过期文件，再更新当日基准
let currentDay = localDay();
function ensureDay() {
  const d = localDay();
  if (d !== currentDay) {
    maintain();
    currentDay = d;
  }
  return d;
}

export function honeylog(): Plugin {
  return {
    name: 'honeydesk-frontend-log',
    apply: 'serve',                                    // 仅 dev server，build 不落盘
    configureServer(server: any) {
      ensureDay();

      // 前端容器每次收到 HTTP 请求（含 /api 代理、HMR）都记录
      server.httpServer?.on('request', (req: any, res: any) => {
        if (!req.url || req.url.startsWith('/__honeylog')) return;
        const start = Date.now();
        res.on('finish', () => {
          const day = ensureDay();
          writeLine(day, `[web] ${req.method} ${req.url} ${res.statusCode} ${Date.now() - start}ms`);
        });
      });

      // 浏览器运行错误上报接口（src/log.ts 通过 sendBeacon 上报）
      server.middlewares.use('/__honeylog', (req: any, res: any) => {
        let body = '';
        req.on('data', (c: Buffer) => (body += c.toString()));
        req.on('end', () => {
          const day = ensureDay();
          writeLine(day, `[browser ${new Date().toISOString()}] ${(body || '').slice(0, 2000)}`);
          res.statusCode = 204;
          res.end();
        });
      });
    },
  };
}