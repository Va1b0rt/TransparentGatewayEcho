"""Bounded diagnostic HTTP backend, reachable only by the bundled TLS proxy."""
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HEADERS = ('host', 'user-agent', 'x-request-id', 'forwarded', 'x-forwarded-for',
           'x-real-ip', 'via', 'client-ip', 'x-client-ip', 'true-client-ip',
           'x-cluster-client-ip', 'x-original-forwarded-for')


class RateLimiter:
    def __init__(self, limit=60, period=60, capacity=10000, clock=time.monotonic):
        if min(limit, period, capacity) <= 0:
            raise ValueError('positive rate settings required')
        self.limit, self.period, self.capacity, self.clock = limit, period, capacity, clock
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def allow(self, peer):
        address = ipaddress.ip_address(peer)
        key = str(address) if address.version == 4 else str(ipaddress.ip_network(str(address)+'/64', strict=False))
        now = self.clock()
        with self.lock:
            while self.entries and next(iter(self.entries.values()))[0]+self.period <= now:
                self.entries.popitem(last=False)
            if key not in self.entries:
                if len(self.entries) >= self.capacity:
                    return False
                self.entries[key] = [now, 0]
            entry = self.entries[key]
            if entry[1] >= self.limit:
                return False
            entry[1] += 1
            return True


class Handler(BaseHTTPRequestHandler):
    server_version = 'TG-Echo/1'
    sys_version = ''

    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, *args):
        pass

    def reply(self, status, payload, extra=None, log=True):
        identifier = uuid.uuid4().hex
        body = (json.dumps({'request_id': identifier, **payload}, separators=(',', ':'))+'\n').encode()
        self.send_response(status)
        for key, value in {'Content-Type':'application/json', 'Content-Length':str(len(body)),
                'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                'X-Request-ID':identifier, 'X-Robots-Tag':'noindex, nofollow',
                'Connection':'close', **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        self.close_connection = True
        if log:
            # Generated ID and status only: never IP, URL, headers, auth or client ID.
            print(json.dumps({'event':'request', 'request_id':identifier, 'status':status}), flush=True)

    def send_error(self, code, message=None, explain=None):
        self.reply(code, {'error':'invalid_request'})

    def do_GET(self):
        try:
            if self.path == '/healthz' and self.client_address[0] == '127.0.0.1':
                self.reply(200, {'status':'ok'}, log=False)
                return
            peer = str(ipaddress.ip_address(self.headers.get('X-TG-Peer', '')))
            if not self.server.limiter.allow(peer):
                self.reply(429, {'error':'rate_limited'}, {'Retry-After':str(self.server.limiter.period)})
                return
            if self.command != 'GET':
                self.reply(405, {'error':'method_not_allowed'}, {'Allow':'GET'})
                return
            url = urlsplit(self.path)
            if url.path != '/':
                self.reply(404, {'error':'not_found'})
                return
            if url.query or self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length', '0')):
                self.reply(400, {'error':'query_or_body_not_supported'})
                return
            headers = {}
            for name in HEADERS:
                value = self.headers.get('X-TG-Original-XFF' if name == 'x-forwarded-for' else name)
                if value:
                    if len(value) > 2048:
                        self.reply(431, {'error':'diagnostic_header_too_large'})
                        return
                    headers[name] = value
            self.reply(200, {'backend_peer':peer, 'headers':headers, 'method':'GET',
                             'peer_source':'caddy_tcp_peer'})
        except (ValueError, TypeError):
            self.reply(400, {'error':'invalid_request'})
        except (OSError, socket.timeout):
            self.close_connection = True

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, limiter):
        self.limiter = limiter
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        print('{"event":"handler_error"}', flush=True)


if __name__ == '__main__':
    limiter = RateLimiter(limit=int(os.getenv('RATE_LIMIT', '60')), period=int(os.getenv('RATE_PERIOD', '60')))
    Server(('0.0.0.0', 8080), limiter).serve_forever()
