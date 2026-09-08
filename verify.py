#!/usr/bin/env python3
"""Verify an owned echo endpoint over certificate-verified HTTPS."""
import argparse
import ipaddress
import json
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid


class ResponseFormatError(ValueError):
    """Safe transport diagnostics, without response payload or request values."""


def decode_response(body, status, headers, stage):
    try:
        return json.loads(body)
    except (ValueError, UnicodeError):
        content_type = headers.get('Content-Type', '').split(';')[0].strip().lower()
        if content_type not in ('application/json', 'text/html', 'text/plain'):
            content_type = 'other_or_missing'
        ray = headers.get('CF-Ray', '')
        if not re.fullmatch(r'[a-fA-F0-9]{16,32}-[A-Za-z]{3}', ray):
            ray = 'unavailable'
        challenge = headers.get('CF-Mitigated', '') == 'challenge'
        edge_code = re.fullmatch(rb'error code: ([0-9]{4})\s*', body)
        edge_code = int(edge_code.group(1)) if edge_code else None
        raise ResponseFormatError(json.dumps({'stage': stage, 'http_status': status,
            'content_type': content_type, 'cloudflare_challenge': challenge,
            'cf_ray': ray, 'edge_error_code': edge_code}, separators=(',', ':'))) from None


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
    def send(path='',headers=None,method='GET',stage='identity_headers', allow_forbidden=False):
        request=urllib.request.Request(base+path,headers={'User-Agent':'TG-Echo-Verify/1.0', **(headers or {})},method=method)
        try: response=opener.open(request,timeout=15)
        except urllib.error.HTTPError as error: response=error
        with response:
            body=response.read(65537)
            assert len(body)<=65536
            if allow_forbidden and response.status==403:
                return response.status,response.headers,None
            return response.status,response.headers,decode_response(body, response.status, response.headers, stage)
    status,headers,body=send(headers={'X-Request-ID':marker,'Authorization':'Bearer '+marker,
        'Cookie':'private='+marker,'Proxy-Authorization':'Basic '+marker,
        'X-TG-Peer':'192.0.2.123','X-TG-Original-XFF':'spoofed','X-Forwarded-For':'198.51.100.44'})
    assert status==200, 'expected HTTP200; if rate-limited, wait for the configured window'
    peer=ipaddress.ip_address(body['backend_peer'])
    if url.hostname not in ('localhost','127.0.0.1','::1'):
        assert peer.is_global, 'endpoint must receive a public TCP peer'
    assert str(peer)!='192.0.2.123'
    assert body['peer_source'] in ('caddy_tcp_peer','npm_tcp_peer','cloudflare_cf_connecting_ip')
    assert headers.get('X-Request-ID')==body['request_id']
    assert body['headers']['x-request-id']==marker
    if body['peer_source'] in ('caddy_tcp_peer', 'npm_tcp_peer'):
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
    code,_,spoof_body=send(headers={'CF-Connecting-IP':'192.0.2.123'},
                           stage='cf_identity_spoof', allow_forbidden=True)
    if code==403:
        print('PASS forged CF-Connecting-IP rejected with HTTP 403; backend handling not exercised by this probe')
    else:
        assert code==200 and spoof_body['backend_peer']==str(peer), 'forged CF identity changed peer'
        print('PASS forged CF-Connecting-IP did not change source IP')
    for path,method,expected in [('?secret='+marker,'GET',400),('unknown','GET',404),('','POST',405)]:
        code,_,response=send(path,method=method,stage='reject_query' if path.startswith('?') else 'reject_path' if path else 'reject_method')
        assert code==expected and marker not in json.dumps(response)
    print('PASS query/path/method rejection without reflecting supplied data')
    if args.rate_test:
        for _ in range(75):
            code,response_headers,_=send(stage='rate_limit')
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
        if isinstance(error, ResponseFormatError):
            print(str(error))
        raise SystemExit(1)
