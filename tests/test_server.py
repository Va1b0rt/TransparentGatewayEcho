import contextlib
import http.client
import io
import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import RateLimiter, Server


class Tests(unittest.TestCase):
    def test_rate_expiry_ipv6_and_capacity(self):
        now=[0]
        limiter=RateLimiter(limit=1, period=10,capacity=2,clock=lambda:now[0])
        self.assertTrue(limiter.allow('192.0.2.1'))
        self.assertFalse(limiter.allow('192.0.2.1'))
        self.assertTrue(limiter.allow('2001:db8::1'))
        self.assertFalse(limiter.allow('2001:db8::2'))
        self.assertFalse(limiter.allow('192.0.2.2'))
        now[0]=11
        self.assertTrue(limiter.allow('192.0.2.2'))

    def test_response_and_logs(self):
        output=io.StringIO()
        server=Server(('127.0.0.1',0),RateLimiter(limit=10))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with contextlib.redirect_stdout(output):
                connection=http.client.HTTPConnection(*server.server_address)
                connection.request('GET','/',headers={'X-TG-Peer':'203.0.113.1','X-TG-Original-XFF':'192.0.2.1',
                    'Authorization':'Bearer test-secret','Cookie':'test-cookie','Proxy-Authorization':'test-proxy-secret',
                    'X-Request-ID':'test-correlation'})
                response=connection.getresponse()
                data=json.loads(response.read())
                self.assertEqual(response.status,200)
                self.assertEqual(data['backend_peer'],'203.0.113.1')
                self.assertEqual(data['headers']['x-forwarded-for'],'192.0.2.1')
                self.assertEqual(data['request_id'],response.getheader('X-Request-ID'))
                self.assertNotIn('test-secret',json.dumps(data))
                connection.close()
        finally:
            server.shutdown();server.server_close();thread.join()
        row=json.loads(output.getvalue())
        self.assertEqual(set(row),{'event','request_id','status'})
        self.assertNotIn('test-correlation',output.getvalue())
        self.assertNotIn('203.0.113.1',output.getvalue())

if __name__=='__main__': unittest.main()
