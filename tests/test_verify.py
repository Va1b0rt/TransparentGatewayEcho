import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify import decode_response, ResponseFormatError


class Diagnostics(unittest.TestCase):
    def test_edge_failure_diagnostics_hide_untrusted_values(self):
        secret = 'private-canary-value'
        with self.assertRaises(ResponseFormatError) as caught:
            decode_response(('<html>'+secret+'</html>').encode(), 403,
                            {'Content-Type': secret, 'CF-Ray': secret}, 'identity_headers')
        self.assertNotIn(secret, str(caught.exception))
        fields = json.loads(str(caught.exception))
        self.assertEqual(fields['http_status'], 403)
        self.assertEqual(fields['stage'], 'identity_headers')

    def test_cloudflare_plaintext_error_is_reported(self):
        with self.assertRaises(ResponseFormatError) as caught:
            decode_response(b'error code: 1010\n', 403,
                            {'Content-Type': 'text/plain; charset=UTF-8'}, 'identity_headers')
        self.assertEqual(json.loads(str(caught.exception))['edge_error_code'], 1010)
