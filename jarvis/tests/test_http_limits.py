import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from agent.data import DataSource
from agent.vault import KnowledgeIndex
from agent.server import make_server

class HTTPLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.server=make_server(KnowledgeIndex(DataSource(Path(self.temp.name),True)).build(),port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_duplicate_host_is_rejected(self):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.putrequest('GET','/api/graph',skip_host=True)
        connection.putheader('Host',f'localhost:{self.server.server_port}')
        connection.putheader('Host','foreign.example')
        connection.endheaders()
        response=connection.getresponse()
        self.assertEqual(response.status,403);response.read();connection.close()
    def test_exhausted_http_slots_fail_fast(self):
        for _ in range(32):self.assertTrue(self.server.request_slots.acquire(blocking=False))
        try:
            connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
            connection.request('GET','/api/graph')
            response=connection.getresponse()
            self.assertEqual(response.status,503);response.read();connection.close()
        finally:
            for _ in range(32):self.server.request_slots.release()
