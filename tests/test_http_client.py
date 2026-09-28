from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread
import unittest

from src.jev_feishu.http_client import ModelError, get_json, post_json, post_stream
from io import BytesIO
from unittest.mock import Mock, patch


class HttpClientTests(unittest.TestCase):
    def test_sse_multiline_unicode_comments_and_done(self):
        body = ': keepalive\r\ndata: {"text":\r\ndata: "虚构"}\r\n\r\ndata: [DONE]\n\n'
        opener = Mock()
        opener.open.return_value = BytesIO(body.encode())
        with patch('src.jev_feishu.http_client.request.build_opener', return_value=opener):
            self.assertEqual(list(post_stream('https://example.com', {}, {}, 2)), [{"text": "虚构"}])

    def test_sse_bad_json_is_sanitized(self):
        opener = Mock()
        opener.open.return_value = BytesIO(b'data: private invalid provider body\n\n')
        with patch('src.jev_feishu.http_client.request.build_opener', return_value=opener):
            with self.assertRaisesRegex(ModelError, '^invalid_response$'):
                list(post_stream('https://example.com', {}, {}, 2))

    def test_redirects_never_receive_our_key_or_payload_and_errors_are_sanitized(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_GET(self):
                calls.append((self.path, self.headers.get('Authorization')))
                if self.path == '/redirect':
                    self.send_response(302); self.send_header('Location', '/untrusted'); self.end_headers()
                elif self.path == '/denied':
                    self.send_response(401); self.end_headers(); self.wfile.write(b'sensitive provider message')
                else:
                    self.send_response(200); self.end_headers(); self.wfile.write(json.dumps({'data': []}).encode())
            do_POST = do_GET
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            for fn in (lambda: get_json(base+'/redirect', 2, headers={'Authorization': 'Bearer fixture-key'}),
                       lambda: post_json(base+'/redirect', {'Authorization': 'Bearer fixture-key'}, {'text':'fixture'}, 2),
                       lambda: list(post_stream(base+'/redirect', {'Authorization': 'Bearer fixture-key'}, {'text':'fixture'}, 2))):
                with self.assertRaisesRegex(ModelError, '^http_error$'): fn()
            self.assertEqual([p for p, _ in calls], ['/redirect', '/redirect', '/redirect'])
            with self.assertRaisesRegex(ModelError, '^unauthorized$'): get_json(base+'/denied', 2)
            self.assertEqual(get_json(base+'/ok', 2), {'data': []})
        finally:
            server.shutdown(); server.server_close(); thread.join()
