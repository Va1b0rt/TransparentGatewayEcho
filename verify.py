#!/usr/bin/env python3
"""Verify an owned echo endpoint over certificate-verified HTTPS."""
import argparse
import ipaddress
import json
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('unexpected redirect')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--ca-file',help='Explicit CA file for the localhost integration test only')
    parser.add_argument('--rate-test',action='store_true',help='Send up to 75 sequential requests to confirm HTTP 429')
    args=parser.parse_args()
    url=urlsplit(args.url)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('use the HTTPS root URL without credentials or query')
    context=ssl.create_default_context(cafile=args.ca_file)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=context))
    base=args.url.rstrip('/')+'/'
    marker=uuid.uuid4().hex
    def send(path='',headers=None,method='GET'):
        request=urllib.request.Request(base+path,headers=headers or {},method=method)
        try: response=opener.open(request,timeout=15)
        except urllib.error.HTTPError as error: response=error
        with response:
            body=response.read(65537)
            assert len(body)<=65536
            return response.status,response.headers,json.loads(body)
    status,headers,body=send(headers={'X-Request-ID':marker,'Authorization':'Bearer '+marker,
        'Cookie':'private='+marker,'Proxy-Authorization':'Basic '+marker,
        'CF-Connecting-IP':'192.0.2.123','X-TG-Peer':'192.0.2.123','X-TG-Original-XFF':'spoofed','X-Forwarded-For':'198.51.100.44'})
    assert status==200, 'expected HTTP200; if rate-limited, wait for the configured window'
    peer=ipaddress.ip_address(body['backend_peer'])
    if url.hostname not in ('localhost','127.0.0.1','::1'):
        assert peer.is_global, 'endpoint must receive a public TCP peer'
    assert str(peer)!='192.0.2.123'
    assert body['peer_source'] in ('caddy_tcp_peer','cloudflare_cf_connecting_ip')
    assert headers.get('X-Request-ID')==body['request_id']
    assert body['headers']['x-request-id']==marker
    if body['peer_source']=='caddy_tcp_peer':
        assert body['headers']['x-forwarded-for']=='198.51.100.44'
    else:
        assert body['headers_view']=='after_cloudflare'
        assert body['headers']['x-forwarded-for'].split(',')[0].strip()=='198.51.100.44'
    assert not any(k in body['headers'] for k in ['authorization','cookie','proxy-authorization','x-tg-peer','x-tg-original-xff'])
    assert headers.get('Cache-Control')=='no-store'
    assert headers.get('Strict-Transport-Security')
    print('PASS HTTPS certificate and hostname verification; HTTP 200')
    print('PASS source IP='+str(peer)+'; source='+body['peer_source']+'; spoofed peer rejected')
    print('PASS diagnostic headers and fresh request ID='+body['request_id'])
    print('PASS Authorization/Cookie/Proxy-Authorization excluded; no-store enabled')
    for path,method,expected in [('?secret='+marker,'GET',400),('unknown','GET',404),('','POST',405)]:
        code,_,response=send(path,method=method)
        assert code==expected and marker not in json.dumps(response)
    print('PASS query/path/method rejection without reflecting supplied data')
    if args.rate_test:
        for _ in range(75):
            code,response_headers,_=send()
            if code==429:
                assert int(response_headers['Retry-After'])>0
                print('PASS rate limit: HTTP 429 and Retry-After')
                break
            assert code==200
        else: raise ValueError('no HTTP 429 within 75 requests; check rate settings')
    print('PUBLIC_ECHO_CHECK PASS' if url.hostname!='localhost' else 'LOCAL_TLS_ECHO_CHECK PASS')


if __name__=='__main__':
    try: main()
    except Exception as error:
        print('ECHO_CHECK FAILED: '+type(error).__name__+'; no response payload displayed')
        raise SystemExit(1)
