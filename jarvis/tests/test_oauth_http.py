"""Local OAuth callback protocol tests; Google responses are explicit doubles."""
import http.client
import json
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from agent.conversation import Assistant
from agent.credentials import TokenStore
from agent.data import DataSource
from agent.integrations import Integrations, SCOPES
from agent.server import make_server
from agent.vault import KnowledgeIndex

class OAuthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        index=KnowledgeIndex(DataSource(self.root,False)).build()
        self.api=Integrations(index)
        self.api.store.root=self.root/'auth'
        self.api.client_id='test-client';self.api.client_secret='test-client-secret'
        self.assistant=Assistant(index,integrations=self.api)
        self.server=make_server(index,port=0,assistant=self.assistant)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        status,headers,body=self.request('/api/session')
        self.headers={'Cookie':headers['Set-Cookie'].split(';')[0],'X-Jarvis-CSRF':json.loads(body)['csrf'],'Content-Type':'application/json'}

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path,payload=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST' if payload is not None else 'GET',path,body=json.dumps(payload) if payload is not None else None,headers=headers or {})
        response=connection.getresponse();body=response.read();result=response.status,dict(response.getheaders()),body
        connection.close();return result

    def finish(self,identifier):
        for _ in range(100):
            status,_,raw=self.request('/api/jobs/'+identifier,headers=self.headers)
            self.assertEqual(status,200)
            data=json.loads(raw)
            if data['state']=='done':return data['result']
            time.sleep(.01)
        self.fail('OAuth job did not complete')

    def begin(self):
        status,_,raw=self.request('/api/oauth/begin',{'service':'gmail','approved':True},self.headers)
        self.assertEqual(status,202)
        outcome=self.finish(json.loads(raw)['job'])
        self.assertTrue(outcome['ok'])
        return urllib.parse.parse_qs(urllib.parse.urlsplit(outcome['authorization_url']).query)['state'][0]

    def test_csrf_approval_and_callback_without_cookie(self):
        self.assertEqual(self.request('/api/oauth/begin',{'service':'gmail','approved':True},{'Content-Type':'application/json'})[0],403)
        state=self.begin()
        token={'access_token':'test-access','token_type':'Bearer','scope':SCOPES['gmail'],'expires_in':3600}
        with patch.object(self.api,'_json',return_value=token) as exchange:
            # SameSite=Strict cookie is intentionally absent on Google's top-level redirect.
            path='/oauth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'test-private-code'})
            status,_,body=self.request(path,headers={'Sec-Fetch-Site':'cross-site'})
            self.assertEqual(status,200)
            self.assertNotIn(b'test-access',body);self.assertNotIn(b'test-private-code',body)
            self.assertTrue(self.api.store.has('gmail'))
            self.assertEqual(self.request(path,headers={'Sec-Fetch-Site':'cross-site'})[0],400)
            exchange.assert_called_once()

    def test_clear_cancels_pending_authorization(self):
        state=self.begin()
        self.assertEqual(self.request('/api/clear',{},self.headers)[0],200)
        self.assertNotIn(state,self.api.pending)
        self.assertEqual(self.request('/oauth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'test'}))[0],400)

    def test_unsupported_account_operations_rejected(self):
        for action in ['send_email','delete_email','create_event','purchase']:
            self.assertEqual(self.request('/api/integrations/run',{'action':action},self.headers)[0],400)
        status,_,raw=self.request('/api/integrations/run',{'action':'read_inbox'},self.headers)
        self.assertEqual(status,202)
        outcome=self.finish(json.loads(raw)['job'])
        self.assertFalse(outcome['ok'])
        self.assertEqual(outcome['error_code'],'authorization')

class EncryptedStorageTests(unittest.TestCase):
    def test_windows_storage_uses_only_encrypted_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=TokenStore();store.root=Path(temporary)/'private'
            token={'access_token':'TEST PRIVATE TOKEN'}
            def protect(data,*,decrypt=False):
                return json.dumps(token).encode() if decrypt else b'ENCRYPTED TEST FIXTURE ONLY'
            with patch('agent.credentials.os.name','nt'),patch('agent.credentials.dpapi',side_effect=protect):
                store.save('gmail',token)
                raw=(store.root/'gmail.dpapi').read_bytes()
                self.assertNotIn(b'TEST PRIVATE TOKEN',raw)
                store.memory.clear()
                self.assertEqual(store.load('gmail'),token)
                store.delete('gmail')
                self.assertFalse((store.root/'gmail.dpapi').exists())

    def test_encryption_failure_never_writes_plaintext(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=TokenStore();store.root=Path(temporary)/'private'
            with patch('agent.credentials.os.name','nt'),patch('agent.credentials.dpapi',side_effect=OSError('Test encryption failure')):
                with self.assertRaises(OSError):store.save('gmail',{'access_token':'TEST PRIVATE TOKEN'})
            self.assertFalse(list(store.root.glob('*')))
