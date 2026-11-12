"""Offline wire tests: every HTTP request stays on a local fake server."""
import gzip
import http.server
import json
import os
import runpy
import socket
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.parse

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin' / 'ade-web'
ARTICLE = 'A complete source article with evidence and references.'


@pytest.fixture
def wire(tmp_path):
    routes, calls = {}, []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            self.do_GET()

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            calls.append((path, self.headers.get('Authorization')))
            status, body, headers = routes.get(path, (503, b'', {}))
            if isinstance(body, dict) or isinstance(body, list):
                body = json.dumps(body).encode()
            if isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            if headers.get('X-Test-Drip'):
                try:
                    for byte in body:
                        self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    # Clear real credentials and proxies; never inherit live provider configuration.
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'PROXY', 'ADE_WEB'))}
    env.update(ADE_WEB_FIRECRAWL_URL=url + '/fc', ADE_WEB_JINA_URL=url + '/jina',
               ADE_WEB_JINA_SEARCH_URL=url + '/search', ADE_WEB_WAYBACK_URL=url + '/archive')
    target = 'http://93.184.216.34:' + str(server.server_port) + '/page'

    def run(command='fetch', value=None, *extra):
        args = [str(CLI), command]
        args += ['--url', value or target] if command == 'check' else [value or target]
        # Test-only transport mapping: validation sees a public IP, socket traffic stays local.
        loader = """
import ipaddress
import runpy
import socket
import sys

class LocalSocket(socket.socket):
    def connect(self, address):
        if address[0] == '93.184.216.34':
            address = ('127.0.0.1', address[1])
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise OSError('test network blocked')
        return super().connect(address)

socket.socket = LocalSocket
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        proc = subprocess.run([sys.executable, '-I', '-c', loader, *args, '--json', '--timeout', '2', *extra],
                              env=env, capture_output=True, text=True, timeout=25)
        assert proc.stdout, proc.stderr
        return proc, json.loads(proc.stdout)

    yield routes, calls, url, target, env, run, tmp_path
    server.shutdown()
    server.server_close()
    thread.join()


def test_firecrawl_first(wire):
    routes, calls, _, _, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'success': True, 'data': {'markdown': ARTICLE}}, {})
    proc, result = run()
    assert proc.returncode == 0
    assert result['provider'] == 'firecrawl' and result['body'] == ARTICLE
    assert [p for p, _ in calls] == ['/fc/v2/scrape']
    assert 'provider=firecrawl status=ok' in proc.stderr


def test_block_page_walks_to_jina(wire):
    routes, calls, _, target, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'data': {'markdown': 'Just a moment. Verify you are human'}}, {})
    routes['/jina/' + target] = (200, ARTICLE, {})
    proc, result = run()
    assert proc.returncode == 0 and result['provider'] == 'jina'
    assert result['attempts'][0]['error'] == 'block or soft-404'
    assert len(calls) == 2


def test_wayback_gzip_after_primary_failures(wire):
    routes, calls, _, target, _, run, _ = wire
    routes['/archive/web/0id_/' + target] = (200, gzip.compress(('<html><p>' + ARTICLE + '</p></html>').encode()), {'Content-Encoding': 'gzip'})
    proc, result = run()
    assert proc.returncode == 0 and result['body'] == ARTICLE
    assert [a['provider'] for a in result['attempts']] == ['firecrawl', 'jina', 'pdf', 'wayback']


def test_cdx_capture(wire):
    routes, _, _, target, _, run, _ = wire
    stamp = '20261112120000'
    routes['/archive/cdx/search/cdx'] = (200, [['timestamp', 'original'], [stamp, target]], {})
    routes['/archive/web/' + stamp + 'id_/' + target] = (200, ARTICLE, {})
    proc, result = run()
    assert proc.returncode == 0 and result['provider'] == 'wayback-cdx'


def test_all_failed_pause(wire):
    _, _, _, _, _, run, _ = wire
    proc, result = run()
    assert proc.returncode == result['exit_code'] == 5
    assert result['provider'] is None and len(result['attempts']) == 5
    assert 'BLOCKED: web access: all providers failed' in proc.stderr


def test_truncated_copy_keeps_walking(wire):
    routes, _, _, target, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'data': {'markdown': 'X' * 1400}}, {})
    proc, result = run('fetch', target, '--max-bytes', '1024')
    assert proc.returncode == 6 and len(result['body']) == 1024
    assert len(result['attempts']) == 5 and result['attempts'][0]['status'] == 'truncated'
    assert 'pause dependent work' in proc.stderr


def test_complete_later_copy_beats_truncated(wire):
    routes, _, _, target, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'data': {'markdown': ARTICLE, 'truncated': True}}, {})
    routes['/jina/' + target] = (200, ARTICLE, {})
    proc, result = run()
    assert proc.returncode == 0 and result['provider'] == 'jina'


def test_search_empty_falls_to_configured_jina(wire):
    routes, calls, _, _, env, run, _ = wire
    env['JINA_API_KEY'] = 'test-only-sentinel'
    routes['/fc/v2/search'] = (200, {'data': {'web': []}}, {})
    routes['/search/evidence'] = (200, ARTICLE, {})
    proc, result = run('search', 'evidence')
    assert proc.returncode == 0 and result['provider'] == 'jina-search'
    assert calls[-1][1] == 'Bearer test-only-sentinel'
    assert 'test-only-sentinel' not in proc.stdout + proc.stderr


def test_search_firecrawl(wire):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/search'] = (200, {'data': [{'title': 'Evidence', 'url': 'https://example.org', 'description': ARTICLE}]}, {})
    proc, result = run('search', 'evidence')
    assert proc.returncode == 0 and 'https://example.org' in result['body']


def test_keyed_request_never_redirects(wire):
    routes, calls, url, _, env, run, _ = wire
    env['ADE_WEB_FIRECRAWL_KEY'] = 'test-only-sentinel'
    routes['/fc/v2/scrape'] = (302, '', {'Location': url + '/leak'})
    proc, result = run()
    assert result['attempts'][0]['error'] == 'HTTP 302'
    assert '/leak' not in [p for p, _ in calls]
    assert 'test-only-sentinel' not in proc.stdout + proc.stderr


def test_error_body_not_logged(wire):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/scrape'] = (403, 'sensitive-provider-error', {})
    proc, result = run()
    assert 'sensitive-provider-error' not in proc.stdout + proc.stderr
    assert result['attempts'][0]['error'] == 'HTTP 403'


def test_check_probes_all_even_after_success(wire):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'data': {'markdown': ARTICLE}}, {})
    proc, result = run('check')
    assert proc.returncode == 0 and len(result['attempts']) == 5


def test_pdf_magic_branch_and_subprocess(wire):
    routes, _, _, _, env, run, tmp = wire
    routes['/page'] = (200, b'%PDF-1.7\nfake wire fixture', {'Content-Type': 'application/octet-stream'})
    tool = tmp / 'pdftotext'
    tool.write_text('#!/usr/bin/env python3\nprint(' + repr(ARTICLE) + ')\n')
    tool.chmod(0o755)
    env['PATH'] = str(tmp) + os.pathsep + env['PATH']
    proc, result = run()
    assert proc.returncode == 0 and result['provider'] == 'pdf'


def test_non_pdf_never_runs_extractor(wire):
    routes, _, _, _, env, run, tmp = wire
    routes['/page'] = (200, 'not a PDF', {'Content-Type': 'application/pdf'})
    tool = tmp / 'pdftotext'
    marker = tmp / 'ran'
    tool.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
    tool.chmod(0o755)
    env['PATH'] = str(tmp) + os.pathsep + env['PATH']
    proc, result = run()
    assert proc.returncode == 5 and not marker.exists()


def test_optional_crwl(wire):
    _, _, _, target, env, run, tmp = wire
    tool = tmp / 'crwl'
    tool.write_text('#!/usr/bin/env python3\nprint(' + repr(ARTICLE) + ')\n')
    tool.chmod(0o755)
    env['PATH'] = str(tmp) + os.pathsep + env['PATH']
    proc, result = run('fetch', target, '--crwl')
    assert proc.returncode == 5 and result['attempts'][-1]['error'] == 'crwl public-only redirects unavailable'


def test_bad_cdx_timestamp(wire):
    routes, _, _, target, _, run, _ = wire
    routes['/archive/cdx/search/cdx'] = (200, [['timestamp', 'original'], ['../../oops', target]], {})
    proc, result = run()
    assert proc.returncode == 5 and result['attempts'][-1]['error'] == 'invalid archive capture'


def test_invalid_target_and_limits(wire):
    _, calls, _, _, _, run, _ = wire
    proc, result = run('fetch', 'https://user:password@example.org')
    assert proc.returncode == 5 and not calls
    assert 'password' not in proc.stdout + proc.stderr


def test_slow_drip_has_wall_deadline(wire):
    routes, _, _, target, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, ' ' * 200, {'X-Test-Drip': 'yes'})
    started = time.monotonic()
    proc, result = run('fetch', target, '--timeout', '0.15')
    assert time.monotonic() - started < 2
    assert proc.returncode == 5
    assert result['attempts'][0]['error'] == 'request timeout'


def test_search_truncation_walks_to_complete(wire):
    routes, _, _, _, env, run, _ = wire
    env['JINA_API_KEY'] = 'test-only-sentinel'
    routes['/fc/v2/search'] = (200, {'truncated': True, 'data': [{'title': ARTICLE}]}, {})
    routes['/search/evidence'] = (200, ARTICLE, {})
    proc, result = run('search', 'evidence')
    assert proc.returncode == 0 and result['provider'] == 'jina-search'
    assert result['attempts'][0]['status'] == 'truncated'


def test_search_only_truncated_requires_pause(wire):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/search'] = (200, {'data': {'truncated': True, 'web': [{'title': ARTICLE}]}}, {})
    proc, result = run('search', 'evidence')
    assert proc.returncode == 6 and result['truncated']


@pytest.mark.parametrize('target', ['https://[broken', 'https://example.org:bad'])
def test_malformed_target_returns_safe_json(wire, target):
    _, calls, _, _, _, run, _ = wire
    proc, result = run('fetch', target)
    assert proc.returncode == 5 and not calls
    assert 'Traceback' not in proc.stderr


def test_malformed_base_returns_safe_json(wire):
    _, calls, _, _, env, run, _ = wire
    env['ADE_WEB_FIRECRAWL_URL'] = 'https://[broken'
    proc, result = run()
    assert proc.returncode == 5 and not calls
    assert 'Traceback' not in proc.stderr


@pytest.mark.parametrize('target', [
    'http://127.0.0.1/', 'http://localhost/', 'http://10.1.2.3/',
    'http://172.16.0.1/', 'http://192.168.0.1/', 'http://169.254.169.254/latest/meta-data',
    'http://[::1]/', 'http://[fe80::1]/', 'http://[::ffff:127.0.0.1]/', 'http://2130706433/',
])
def test_nonpublic_target_never_reaches_provider(wire, target):
    _, calls, _, _, _, run, _ = wire
    proc, result = run('fetch', target)
    assert proc.returncode == 5 and not calls and result['untrusted'] is True
    assert 'non-public target blocked' in proc.stderr


def test_keyless_provider_redirect_cannot_reach_private(wire):
    routes, calls, url, target, _, run, _ = wire
    routes['/jina/' + target] = (302, '', {'Location': url + '/metadata'})
    routes['/metadata'] = (200, ARTICLE, {})
    proc, result = run()
    assert proc.returncode == 5
    assert '/metadata' not in [p for p, _ in calls]
    assert result['attempts'][1]['error'] == 'non-public target blocked'


def test_direct_pdf_redirect_cannot_reach_private(wire):
    routes, calls, _, _, _, run, _ = wire
    routes['/page'] = (302, '', {'Location': 'http://169.254.169.254/latest/meta-data'})
    proc, result = run()
    assert proc.returncode == 5
    assert result['attempts'][2]['error'] == 'non-public target blocked'


@pytest.mark.parametrize('phrase', ['captcha solving', 'access denied', '404 not found'])
def test_search_allows_block_phrase_results(wire, phrase):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/search'] = (200, {'data': [{'title': phrase}]}, {})
    proc, result = run('search', phrase)
    assert proc.returncode == 0 and phrase in result['body']
    assert result['untrusted'] is True


def test_successful_fetch_is_untrusted(wire):
    routes, _, _, _, _, run, _ = wire
    routes['/fc/v2/scrape'] = (200, {'data': {'markdown': ARTICLE}}, {})
    proc, result = run()
    assert proc.returncode == 0 and result['untrusted'] is True


def test_mixed_dns_answers_fail_closed(monkeypatch):
    module = runpy.run_path(str(CLI))
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80)),
    ])
    with pytest.raises(module['Failure'], match='non-public target blocked'):
        module['valid_url']('http://mixed.example/', public=True)


def test_direct_connection_pins_validated_address(monkeypatch):
    module = runpy.run_path(str(CLI))
    lookups, connections = [], []

    def addresses(*args, **kwargs):
        lookups.append(args)
        address = '93.184.216.34' if len(lookups) == 1 else '127.0.0.1'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 80))]

    class Socket:
        def __init__(self, *args): pass
        def settimeout(self, seconds): pass
        def connect(self, address): connections.append(address)

    monkeypatch.setattr(socket, 'getaddrinfo', addresses)
    monkeypatch.setattr(socket, 'socket', Socket)
    module['public_connection'](('rebind.example', 80), timeout=1)
    assert len(lookups) == 1 and connections == [('93.184.216.34', 80)]
