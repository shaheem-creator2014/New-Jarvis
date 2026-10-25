"""Loopback-only dashboard, validated assistant requests and explicit static assets."""
import json
import os
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from .data import PROJECT
from .ai import CHAT_MODES
from .conversation import Assistant, BusyError
from .voice import VoiceError, decode_recording
from .integrations import IntegrationError

ASSETS = {'/': ('index.html', 'text/html'), '/styles.css': ('styles.css', 'text/css'),
          '/app.js': ('app.js', 'text/javascript'), '/graph.js': ('graph.js', 'text/javascript'), '/voice.js': ('voice.js', 'text/javascript'), '/integrations.js': ('integrations.js', 'text/javascript'), '/memory.js': ('memory.js', 'text/javascript')}


class LocalServer(ThreadingHTTPServer):
    """Bound socket/request resources separately from the single AI worker."""
    def __init__(self, *args, **kwargs):
        self.request_slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address

    def process_request(self, request, address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except Exception:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.request_slots.release()


def make_server(index, port=8765, assistant=None):
    assistant = assistant or Assistant(index)
    graph = index.neighbors()
    nodes = [{ 'id': key, 'title': doc.title, 'type': doc.kind,
               'category': key.split('/')[0], 'connections': len(graph[key]),
               'summary': doc.text[:800], 'related': sorted(graph[key]) }
             for key, doc in index.documents.items()]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Avoid retaining personal search queries or conversation content in logs.
            pass

        def respond(self, status, payload, mime='application/json', cookie=None):
            body = json.dumps(payload, ensure_ascii=False).encode() if mime == 'application/json' else payload
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if cookie:
                self.send_header('Set-Cookie', f'jarvis_session={cookie}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_request(self, *, oauth_callback=False):
            authority = f'127.0.0.1:{self.server.server_port}'
            allowed = {authority, f'localhost:{self.server.server_port}'}
            if len(self.headers.get_all('Host',[])) != 1 or self.headers.get('Host') not in allowed:
                return False
            if oauth_callback:
                return True  # OAuth state+PKCE protect this Google top-level redirect.
            if len(self.headers.get_all('Origin',[])) > 1:
                return False
            origin = self.headers.get('Origin')
            if origin and origin not in {'http://' + host for host in allowed}:
                return False
            return self.headers.get('Sec-Fetch-Site') not in {'cross-site', 'same-site'}

        def current_session(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                item = cookie.get('jarvis_session')
                identifier = item.value if item else None
            except Exception:
                identifier = None
            return assistant.session(identifier)

        def do_GET(self):
            if not self.path.startswith('/') or self.path.startswith('//'):
                return self.respond(400, {'error':'Use a local request path'})
            callback = self.path.split('?',1)[0] == '/oauth/google/callback'
            if not self.valid_request(oauth_callback=callback):
                return self.respond(403, {'error': 'Local same-origin requests only'})
            if len(self.path) > 4096:
                return self.respond(414, {'error': 'Request too long'})
            url = urlsplit(self.path)
            if callback:
                try:
                    params = parse_qs(url.query, max_num_fields=10)
                    service = assistant.integrations.finish(params)
                    content = f'<!doctype html><html lang="en"><meta charset="utf-8"><title>JARVIS authorization</title><p>{service.title()} authorization saved. Return to JARVIS and refresh account status. No messages or events were modified.</p></html>'
                    return self.respond(200, content.encode(), 'text/html')
                except (IntegrationError, ValueError, OSError):
                    return self.respond(400, b'<!doctype html><html lang="en"><meta charset="utf-8"><title>JARVIS authorization failed</title><p>Google authorization failed, was declined, or expired. No new authorization is claimed. Return to JARVIS and start again.</p></html>', 'text/html')
            if url.path == '/api/integrations/status':
                return self.respond(200, assistant.integrations.status())
            if url.path in ASSETS:
                name, mime = ASSETS[url.path]
                return self.respond(200, (PROJECT / 'ui' / name).read_bytes(), mime)
            if url.path == '/api/session':
                try:
                    identifier, session = self.current_session()
                except BusyError as error:
                    return self.respond(429, {'error': str(error)})
                return self.respond(200, {'csrf': session['csrf'], 'history': assistant.history(session)}, cookie=identifier)
            if url.path == '/api/status':
                return self.respond(200, {'ollama': assistant.ai.status(), 'microphone': 'inactive',
                    'demo': index.source.demo, 'platform': os.name, 'voice': assistant.voice.status(), 'integrations': assistant.integrations.status()})
            if url.path.startswith('/api/jobs/'):
                try:
                    identifier, _ = self.current_session()
                except BusyError as error:
                    return self.respond(429, {'error': str(error)})
                with assistant.lock:
                    job = assistant.jobs.get(url.path.removeprefix('/api/jobs/'))
                    if job is None or job['session'] != identifier:
                        return self.respond(404, {'error': 'Job not found for this session'})
                    payload = {'state': job['state']}
                    if job['state'] == 'done':
                        payload['result'] = dict(job['result'])
                        if 'audio' in job['result']:
                            job['result'].pop('audio')
                            job['result']['audio_consumed'] = True
                return self.respond(200, payload)
            if url.path == '/api/graph':
                return self.respond(200, {'nodes': nodes, 'edges': sorted(index.edges),
                    'demo': index.source.demo, 'skipped': index.skipped, 'warnings': index.warnings})
            if url.path == '/api/search':
                try:
                    args = parse_qs(url.query, max_num_fields=5)
                except ValueError:
                    return self.respond(400, {'error': 'Too many query fields'})
                if set(args) - {'q'} or len(args.get('q', [])) != 1 or len(args['q'][0]) > 300:
                    return self.respond(400, {'error': 'Supply one search query of 1–300 characters'})
                return self.respond(200, {'results': index.search(args['q'][0])})
            return self.respond(404, {'error': 'Not found'})

        def do_POST(self):
            self.close_connection = True
            if not self.valid_request():
                return self.respond(403, {'error': 'Local same-origin requests only'})
            if self.path not in {'/api/chat', '/api/model', '/api/confirm', '/api/plan', '/api/clear', '/api/voice/transcribe', '/api/voice/speak', '/api/oauth/begin', '/api/oauth/disconnect', '/api/integrations/run', '/api/memory/run'}:
                return self.respond(405, {'error': 'Unsupported operation'})
            if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                return self.respond(415, {'error': 'Use application/json with Content-Length'})
            try:
                identifier, session = self.current_session()
                csrf = self.headers.get('X-Jarvis-CSRF', '')
                if not csrf or not secrets.compare_digest(csrf, session['csrf']):
                    return self.respond(403, {'error': 'Missing or invalid session security token'})
                if len(self.headers.get_all('Content-Length',[])) != 1:
                    raise ValueError('Supply exactly one Content-Length')
                length = int(self.headers.get('Content-Length', '0'))
                limit = 9 * 1024 * 1024 if self.path == '/api/voice/transcribe' else 20000
                if not 1 <= length <= limit:
                    return self.respond(413, {'error': f'Request must contain 1–{limit} bytes'})
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete request body')
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                if self.path == '/api/memory/run':
                    action = body.get('action')
                    if action == 'list' and set(body)=={'action'}:
                        pass
                    elif action == 'save' and set(body)=={'action','fact','approved','sensitive','sensitive_approved','kind'}:
                        if any(type(body[key]) is not bool for key in ['approved','sensitive','sensitive_approved']) or not isinstance(body['kind'],str):
                            raise ValueError('Memory approval fields must be booleans and kind must be text')
                    elif action == 'delete' and set(body)=={'action','id','approved'} and type(body['approved']) is bool:
                        pass
                    else:
                        raise ValueError('Invalid memory operation or fields')
                    operation = lambda: assistant.memory_action(session,body)
                elif self.path == '/api/oauth/begin':
                    if set(body) != {'service','approved'} or not isinstance(body['service'],str):
                        raise ValueError('Choose a service and explicitly approve authorization')
                    operation = lambda: assistant.integrations.begin(body['service'], identifier, self.server.server_port, approved=body['approved'])
                elif self.path == '/api/oauth/disconnect':
                    if set(body) != {'service','approved'} or body['approved'] is not True or not isinstance(body['service'],str):
                        raise ValueError('Choose a service and explicitly approve disconnect')
                    operation = lambda: assistant.disconnect(body['service'], session)
                elif self.path == '/api/integrations/run':
                    if not isinstance(body.get('action'),str):
                        raise ValueError('Choose an integration action')
                    action = body['action']
                    if action == 'research_web':
                        if set(body) != {'action','query','approved'}:
                            raise ValueError('Research needs a query and explicit approval')
                        operation = lambda: assistant.integrations.research(body['query'], approved=body['approved'])
                    elif action == 'google_calendar':
                        if set(body) != {'action','horizon','query'}:
                            raise ValueError('Calendar needs horizon and query')
                        operation = lambda: assistant.integrations.calendar(horizon=body['horizon'],query=body['query'])
                    elif action in {'read_inbox','brief_me'} and set(body)=={'action'}:
                        operation = lambda: assistant.integration_action(session,action)
                    else:
                        raise ValueError('Unsupported integration action')
                elif self.path == '/api/voice/transcribe':
                    if set(body) != {'audio', 'mime', 'approved'}:
                        raise ValueError('Supply audio, mime and explicit approved=true')
                    assistant.voice.authorize(body['approved'])
                    audio, mime = decode_recording(body['audio'], body['mime'])
                    operation = lambda: assistant.transcribe(audio, mime, body['approved'])
                elif self.path == '/api/voice/speak':
                    if set(body) != {'job', 'approved'} or not isinstance(body['job'], str) or len(body['job']) > 100:
                        raise ValueError('Supply a completed response job and explicit approval')
                    assistant.voice.authorize(body['approved'], tts=True)
                    operation = lambda: assistant.speak(identifier, body['job'], body['approved'])
                elif self.path == '/api/model':
                    if set(body) != {'model'} or not isinstance(body['model'], str) or not 1 <= len(body['model']) <= 200:
                        raise ValueError('Supply only the installed model name')
                    operation = lambda: assistant.select_model(body['model'])
                elif self.path == '/api/chat':
                    if set(body) != {'text', 'mode'} or body['mode'] not in CHAT_MODES or not isinstance(body['text'], str) or not 1 <= len(body['text'].strip()) <= 4000:
                        raise ValueError('Supply text (1–4000 characters) and a supported conversation or subject mode')
                    operation = lambda: assistant.process(session, body['text'].strip(), body['mode'])
                elif self.path == '/api/confirm':
                    if set(body) != {'token', 'approved'} or not isinstance(body['token'], str) or len(body['token']) > 100 or type(body['approved']) is not bool:
                        raise ValueError('Supply confirmation token and boolean approved')
                    operation = lambda: assistant.confirm(session, body['token'], body['approved'])
                elif self.path == '/api/plan':
                    if set(body) != {'tasks'}:
                        raise ValueError('Supply only tasks')
                    from .tools import plan_day
                    plan_day(body['tasks'])  # Validate before queuing.
                    operation = lambda: assistant.plan(session, body['tasks'])
                else:
                    if body:
                        raise ValueError('Clear expects an empty object')
                    with assistant.lock:
                        if session['busy']:
                            raise BusyError('Wait for the active request before clearing history')
                        session['history'].clear()
                        session['pending'].clear()
                        session['tasks'] = []
                        with assistant.integrations.lock:
                            assistant.integrations.pending = {key:value for key,value in assistant.integrations.pending.items() if value['session'] != identifier}
                        assistant.jobs = {key: job for key, job in assistant.jobs.items() if job['session'] != identifier}
                    return self.respond(200, {'cleared': True})
                job = assistant.submit(identifier, session, operation)
                return self.respond(202, {'job': job})
            except IntegrationError as error:
                return self.respond(403 if error.code in {'approval_required','demo_blocked'} else 503, {'error':str(error),'error_code':error.code})
            except VoiceError as error:
                return self.respond(403 if error.code in {'demo_blocked', 'approval_required'} else 503, {'error': str(error), 'error_code': error.code})
            except BusyError as error:
                return self.respond(429, {'error': str(error)})
            except (ValueError, TypeError, KeyError, UnicodeError, OSError) as error:
                return self.respond(400, {'error': 'Invalid request: ' + str(error)[:200]})

    server = LocalServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.assistant = assistant
    return server
