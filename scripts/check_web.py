#!/usr/bin/env python3
"""Local production-Caddy browser smoke with synthetic credentials and disposable TLS."""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BROWSER = r'''
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { join } from 'node:path';
const [url, workspace] = process.argv.slice(2);
const { chromium } = createRequire(join(workspace, 'package.json'))('@playwright/test');
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ ignoreHTTPSErrors: true }); // Disposable localhost certificate only.
  await context.route('https://telegram.org/**', r => r.fulfill({ contentType: 'application/javascript', body: '' }));
  await context.route('**/api/**', r => r.fulfill({ status: 503, contentType: 'application/json', body: '{"error":{"code":"server_error"}}' }));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error' && /Content Security Policy|Refused to execute inline/i.test(m.text())) errors.push(m.text()); });
  for (const path of ['/', '/app', '/privacy']) {
    const response = await page.goto(url + path, { waitUntil: 'domcontentloaded' });
    assert.equal(response.status(), 200);
    assert.ok(response.headers()['content-security-policy'].includes("'sha256-"));
    await page.waitForFunction(() => Object.keys(window).some(k => k.startsWith('__sveltekit_')), null, { timeout: 5000 });
    await page.waitForTimeout(300);
  }
  await context.route('https://*.game.example.com/routing/ping*', r => {
    const headers = r.request().headers();
    assert.equal(headers['x-telegram-init-data'], undefined);
    assert.equal(headers.authorization, undefined);
    assert.equal(headers.cookie, undefined);
    return r.fulfill({ contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': new URL(url).origin, 'Cache-Control': 'no-store' }, body: '{"ok":true}' });
  });
  for (const region of ['msk-1', 'kzn', 'spb', 'msk-2']) {
    const ok = await page.evaluate(async id => (await (await fetch(`https://${id}.game.example.com/routing/ping?nonce=smoke`, { credentials: 'omit', cache: 'no-store' })).json()).ok, region);
    assert.equal(ok, true);
  }
  assert.deepEqual(errors, []);
  let untrustedNetwork = 0;
  await context.route('https://untrusted.invalid/**', r => { untrustedNetwork++; return r.fulfill({ body: '{}' }); });
  const blocked = await page.evaluate(async () => {
    try { await fetch('https://untrusted.invalid/routing/ping', { headers: { 'X-Telegram-Init-Data': 'synthetic-not-a-secret' } }); return false; }
    catch { return true; }
  });
  assert.equal(blocked, true);
  assert.equal(untrustedNetwork, 0);
  console.log('3 production pages hydrated; CSP hashes and 4 anonymous regional routes passed; untrusted authorization blocked');
} finally { await browser.close(); }
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--web-image', required=True)
    parser.add_argument('--frontend-workspace', type=Path, required=True, help='frontend/web after pnpm install and playwright install chromium')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9./:@_-]+', args.web_image):
        raise SystemExit('invalid image reference')
    workspace = args.frontend_workspace.resolve()
    name = 'mosprom-web-smoke-' + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='mosprom-web-smoke-') as folder:
        root = Path(folder)
        root.chmod(0o755)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=localhost', '-addext',
                        'subjectAltName=DNS:localhost', '-keyout', str(root / 'ingress.key'), '-out', str(root / 'ingress.crt')], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Public test-only key, generated here and destroyed below; no production TLS material is used.
        (root / 'ingress.key').chmod(0o644)
        try:
            subprocess.run(['docker', 'run', '-d', '--name', name, '--label', 'codex.task=mosprom-devops', '--read-only', '--cap-drop=ALL',
                            '--cap-add=NET_BIND_SERVICE', '--tmpfs=/tmp:rw,nosuid,noexec,size=16m', '-p', '127.0.0.1::8443', '-e', 'DOMAIN=https://localhost:8443',
                            '-e', 'TLS_SNIPPET=provided', '-e', 'ACME_EMAIL=ops@example.com', '-e', 'ROUTING_ZONE=game.example.com',
                            '-v', folder + ':/tls:ro', '-v', str(ROOT / 'compose/Caddyfile') + ':/etc/caddy/Caddyfile:ro', args.web_image], check=True, stdout=subprocess.DEVNULL)
            port = subprocess.check_output(['docker', 'port', name, '8443'], text=True).strip().rsplit(':', 1)[1]
            for _ in range(30):
                ready = subprocess.run(['docker', 'exec', name, 'wget', '-q', '--spider', 'http://127.0.0.1:8081/health'], capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('production Caddy did not become ready')
            subprocess.run(['node', '--input-type=module', '-', 'https://localhost:' + port, str(workspace)], input=BROWSER, text=True, env=os.environ, check=True)
        finally:
            subprocess.run(['docker', 'rm', '-f', '-v', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
