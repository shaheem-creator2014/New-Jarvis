import http.client
import json
import threading
import unittest
from agent.data import selected_source
from agent.vault import KnowledgeIndex
from agent.server import make_server

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(KnowledgeIndex(selected_source()).build(), port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, headers=None, method='GET'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        result = response.status, response.getheaders(), response.read()
        conn.close()
        return result

    def test_graph_and_search(self):
        status, _, body = self.request('/api/graph')
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data['demo'])
        self.assertEqual(len(data['nodes']), 13)
        self.assertEqual(len(data['edges']), 35)
        status, _, body = self.request('/api/search?q=ESP32')
        self.assertEqual(status, 200)
        self.assertTrue(any(row['filename'] == 'Robotics/ESP32 Rover.md' for row in json.loads(body)['results']))

    def test_assets_and_privacy(self):
        for path in ['/', '/styles.css', '/app.js', '/graph.js']:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 100)
            self.assertIn('Content-Security-Policy', dict(headers))
        for path in ['/../.env', '/.env', '/agent/data.py', '/data/demo/School/Study%20Plan.md']:
            self.assertEqual(self.request(path)[0], 404)

    def test_request_validation(self):
        for headers in [{'Origin':'https://attacker.example'}, {'Host':'attacker.example'}, {'Sec-Fetch-Site':'cross-site'}]:
            self.assertEqual(self.request('/api/graph', headers)[0], 403)
        for path in ['/api/search', '/api/search?q=one&q=two', '/api/search?q=one&path=secret', '/api/search?q=' + 'x'*301]:
            self.assertEqual(self.request(path)[0], 400)
        self.assertEqual(self.request('/api/graph', method='POST')[0], 405)
