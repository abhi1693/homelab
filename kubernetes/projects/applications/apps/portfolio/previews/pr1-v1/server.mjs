import http from 'node:http';
import { open, realpath, stat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { resolve, sep, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pipeline } from 'node:stream/promises';

export const REVISION = 'e6dcf46fa4ab47014b2910aae8949f0a42f8b72f';
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
  '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.webm': 'video/webm', '.mp4': 'video/mp4',
  '.woff2': 'font/woff2',
};
export async function createPreviewServer(directory) {
  const root = await realpath(directory);
  const inside = (path) => path.startsWith(root + sep);
  const server = http.createServer({ maxHeaderSize: 16384, requestTimeout: 15000,
    headersTimeout: 10000, keepAliveTimeout: 5000, connectionsCheckingInterval: 1000 },
  async (req, res) => {
    res.setHeader('X-Robots-Tag', 'noindex, nofollow, noarchive');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; font-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'");
    res.setHeader('X-Preview-Commit', REVISION);
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    const end = (code, text) => {
      res.statusCode = code;
      res.setHeader('Content-Type', 'text/plain; charset=utf-8');
      res.setHeader('Content-Length', Buffer.byteLength(text));
      res.end(req.method === 'HEAD' ? undefined : text);
    };
    let file;
    try {
      if (!['GET', 'HEAD'].includes(req.method)) {
        res.setHeader('Allow', 'GET, HEAD');
        req.resume(); return end(405, 'Method not allowed\n');
      }
      if (req.headers['transfer-encoding'] || Number(req.headers['content-length'] || 0)) {
        req.resume(); return end(400, 'Request bodies are not supported\n');
      }
      if (!req.url?.startsWith('/') || req.url.startsWith('//') || req.url.length > 4096)
        return end(400, 'Invalid request target\n');
      let path;
      try { path = decodeURIComponent(req.url.split('?', 1)[0]); }
      catch { return end(400, 'Invalid URL encoding\n'); }
      if (/[\x00-\x1f\x7f\\%]/.test(path)) return end(400, 'Invalid path\n');
      if (path.split('/').some(part => part.startsWith('.'))) return end(404, 'Not found\n');
      if (path === '/healthz') return end(200, 'ok\n');
      if (path === '/robots.txt') return end(200, 'User-agent: *\nDisallow: /\n');
      let target = resolve(root, '.' + path);
      if (target !== root && !inside(target)) return end(404, 'Not found\n');
      let canonical = await realpath(target);
      if (canonical !== target || (canonical !== root && !inside(canonical))) return end(404, 'Not found\n');
      const info = await stat(canonical);
      if (info.isDirectory()) {
        if (!path.endsWith('/')) {
          res.setHeader('Location', path.replaceAll('//', '/') + '/');
          return end(308, 'Use the directory URL\n');
        }
        target = resolve(canonical, 'index.html');
        canonical = await realpath(target);
      }
      if (canonical !== target || !inside(canonical) || !MIME[extname(canonical)]) return end(404, 'Not found\n');
      file = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW);
      const details = await file.stat();
      if (!details.isFile()) return end(404, 'Not found\n');
      res.setHeader('Content-Type', MIME[extname(canonical)]);
      res.setHeader('Last-Modified', details.mtime.toUTCString());
      const etag = '"' + details.size.toString(16) + '-' + Math.trunc(details.mtimeMs).toString(16) + '"';
      res.setHeader('ETag', etag);
      res.setHeader('Accept-Ranges', 'bytes');
      if (!path.endsWith('.html') && path !== '/' && !path.endsWith('/'))
        res.setHeader('Cache-Control', 'public, max-age=86400, no-transform');
      if (req.headers['if-none-match']?.split(',').map(s => s.trim()).includes(etag)) {
        res.statusCode = 304; return res.end();
      }
      let start = 0, finish = details.size - 1;
      if (req.headers.range && (!req.headers['if-range'] || req.headers['if-range'] === etag)) {
        const match = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
        let valid = Boolean(match && (match[1] || match[2]));
        if (valid) {
          if (!match[1]) {
            const suffix = Number(match[2]);
            valid = Number.isSafeInteger(suffix) && suffix > 0;
            start = Math.max(0, details.size - suffix);
          } else {
            start = Number(match[1]);
            finish = match[2] ? Math.min(Number(match[2]), finish) : finish;
          }
          valid &&= Number.isSafeInteger(start) && Number.isSafeInteger(finish) &&
            start >= 0 && start < details.size && finish >= start;
        }
        if (!valid) {
          res.setHeader('Content-Range', 'bytes */' + details.size);
          return end(416, 'Unsatisfiable range\n');
        }
        res.statusCode = 206;
        res.setHeader('Content-Range', 'bytes ' + start + '-' + finish + '/' + details.size);
      }
      res.setHeader('Content-Length', Math.max(0, finish - start + 1));
      if (req.method === 'HEAD' || details.size === 0) return res.end();
      await pipeline(file.createReadStream({ start, end: finish, autoClose: false }), res);
    } catch (error) {
      if (!res.headersSent) end(['ENOENT', 'ENOTDIR', 'ELOOP', 'EACCES'].includes(error.code) ? 404 : 500,
        'Not found or unavailable\n');
      else res.destroy();
    } finally { await file?.close().catch(() => {}); }
  });
  server.maxConnections = 256;
  server.maxRequestsPerSocket = 1000;
  server.setTimeout(15000, socket => socket.destroy());
  return server;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const server = await createPreviewServer(fileURLToPath(new URL('./dist/', import.meta.url)));
  server.listen(Number(process.env.PORT || 8080), '0.0.0.0', () => console.log('Static preview listening'));
  process.on('SIGTERM', () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(1), 10000).unref();
  });
}
