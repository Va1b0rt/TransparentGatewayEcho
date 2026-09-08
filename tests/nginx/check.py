import json, urllib.request, urllib.error, uuid, subprocess
marker=uuid.uuid4().hex
url='http://127.0.0.1:18081/'
def send(path='', method='GET', headers=None):
    req=urllib.request.Request(url+path, method=method, headers=headers or {})
    try: response=urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e: response=e
    with response: return response.status, response.headers, json.loads(response.read())
status, headers, body=send(headers={'X-Test-Rewrite':'8.8.8.8', 'CF-Connecting-IP':'9.9.9.9',
    'X-TG-Peer':'173.245.48.10', 'X-TG-Original-XFF':'forged',
    'X-Forwarded-For':'198.51.100.44','X-Real-IP':'192.0.2.33',
    'Authorization':'Bearer '+marker,'X-Request-ID':marker})
assert status==200, status
assert body['peer_source']=='npm_tcp_peer', body
assert body['backend_peer'] not in ('8.8.8.8','9.9.9.9','173.245.48.10'), body
assert body['headers']['x-forwarded-for']=='198.51.100.44'
assert body['headers']['x-real-ip']=='192.0.2.33'
assert body['headers']['x-request-id']==marker
assert 'authorization' not in body['headers']
assert headers['X-Request-ID']==body['request_id']
assert headers['Strict-Transport-Security']
assert headers['Cache-Control']=='no-store'
for path, method, expected in [('?secret='+marker,'GET',400), ('missing','GET',404), ('','POST',405)]:
    assert send(path,method)[0]==expected
for _ in range(10):
    status, headers, body=send()
    if status==429:
        assert int(headers['Retry-After'])>0
        break
else: raise AssertionError('No rate limit')
logs=subprocess.check_output(['sudo','docker','compose','-f','tests/nginx/compose.yaml','logs','--no-color'],stderr=subprocess.STDOUT).decode()
assert marker not in logs, 'private marker logged'
assert '198.51.100.44' not in logs, 'diagnostic IP logged'
print('NPM_NGINX_INTEGRATION PASS: original TCP peer, spoof rejection, headers, privacy, rate limit')
