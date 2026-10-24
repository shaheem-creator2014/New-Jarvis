"""Voice HTTP tests use in-process provider doubles; no external requests."""
import base64
import http.client
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
from agent.conversation import Assistant
from agent.data import selected_source
from agent.server import make_server
from agent.vault import KnowledgeIndex
from agent.voice import ElevenLabs

class VoiceAPITests(unittest.TestCase):
    def setUp(self):
        index=KnowledgeIndex(selected_source()).build()
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test-only-placeholder','ELEVENLABS_VOICE_ID':'test_voice'}):
            self.voice=ElevenLabs(demo=False)
        self.assistant=Assistant(index,voice=self.voice)
        self.server=make_server(index,port=0,assistant=self.assistant)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close)
        status,headers,session=self.request('/api/session')
        self.headers={'Cookie':headers['Set-Cookie'].split(';')[0],'X-Jarvis-CSRF':session['csrf'],'Content-Type':'application/json'}
        self.identifier=self.headers['Cookie'].split('=',1)[1]

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('POST' if body is not None else 'GET',path,body=json.dumps(body) if body is not None else None,headers=headers or {})
        response=connection.getresponse();data=response.read();result=response.status,dict(response.getheaders()),json.loads(data)
        connection.close();return result

    def wait(self,job):
        for _ in range(100):
            status,_,body=self.request('/api/jobs/'+job,headers=self.headers)
            self.assertEqual(status,200)
            if body['state']=='done':return body['result']
            time.sleep(.01)
        self.fail('Voice job did not complete')

    def test_transcription_approval_and_no_audio_in_retained_job(self):
        audio=b'\x1aE\xdf\xa3'+b'test-only-container'*5
        payload={'audio':base64.b64encode(audio).decode(),'mime':'audio/webm','approved':False}
        with patch.object(self.voice,'transcribe',return_value={'ok':True,'tool':'scribe','transcript':'Test transcript only'}) as provider:
            self.assertEqual(self.request('/api/voice/transcribe',payload,self.headers)[0],403)
            provider.assert_not_called()
            payload['approved']=True
            status,_,job=self.request('/api/voice/transcribe',payload,self.headers)
            self.assertEqual(status,202)
            outcome=self.wait(job['job'])
            self.assertEqual(outcome['transcript'],'Test transcript only')
            provider.assert_called_once_with(audio,'audio/webm',approved=True)
            self.assertNotIn('audio',self.assistant.jobs[job['job']]['result'])

    def test_demo_key_and_csrf_guards(self):
        payload={'job':'some-job','approved':True}
        with patch.object(self.voice,'speak') as provider:
            self.assertEqual(self.request('/api/voice/speak',payload,{'Content-Type':'application/json'})[0],403)
            self.voice.demo=True
            status,_,body=self.request('/api/voice/speak',payload,self.headers)
            self.assertEqual(status,403);self.assertEqual(body['error_code'],'demo_blocked')
            self.voice.demo=False;self.voice.key=''
            status,_,body=self.request('/api/voice/speak',payload,self.headers)
            self.assertEqual(status,503);self.assertEqual(body['error_code'],'missing_key')
            provider.assert_not_called()

    def test_audio_delivered_once_and_only_for_owned_source(self):
        self.assistant.jobs['source']={'session':self.identifier,'created':time.monotonic(),'state':'done','result':{'spoken':'Owned response','tool':'chat'}}
        audio=base64.b64encode(b'ID3test-double').decode()
        with patch.object(self.voice,'speak',return_value={'ok':True,'tool':'tts','audio':audio,'mime':'audio/mpeg','spoken':'Generated test double'}):
            status,_,job=self.request('/api/voice/speak',{'job':'source','approved':True},self.headers)
            self.assertEqual(status,202)
            result=self.wait(job['job'])
            self.assertEqual(result['audio'],audio)
            _,_,again=self.request('/api/jobs/'+job['job'],headers=self.headers)
            self.assertNotIn('audio',again['result'])
            self.assertTrue(again['result']['audio_consumed'])
            status,_,job=self.request('/api/voice/speak',{'job':'unknown','approved':True},self.headers)
            self.assertFalse(self.wait(job['job'])['ok'])
