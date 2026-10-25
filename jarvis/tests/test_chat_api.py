import http.client
import json
import threading
import time
import unittest
from unittest.mock import patch
from agent.ai import AIUnavailable
from agent.conversation import Assistant
from agent.data import selected_source
from agent.server import make_server
from agent.vault import KnowledgeIndex

class OfflineAI:
    model='offline-test-double'
    def respond(self,*args,**kwargs):raise AIUnavailable('Ollama unavailable in this test')
    def status(self):return {'connected':False,'model_ready':False,'model':self.model,'message':'Offline test double'}

class ChatAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index=KnowledgeIndex(selected_source()).build()
        cls.assistant=Assistant(cls.index,OfflineAI())
        cls.server=make_server(cls.index,port=0,assistant=cls.assistant)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def request(self,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request('POST' if body is not None else 'GET',path,body=body,headers=headers or {})
        response=conn.getresponse();data=response.read();result=response.status,dict(response.getheaders()),json.loads(data)
        conn.close();return result

    def session(self):
        status,headers,data=self.request('/api/session')
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        return {'Cookie':cookie,'X-Jarvis-CSRF':data['csrf'],'Content-Type':'application/json'}

    def post(self,path,payload,headers):
        return self.request(path,json.dumps(payload),headers)

    def finish(self,job,headers):
        for _ in range(100):
            status,_,result=self.request('/api/jobs/'+job,headers=headers)
            self.assertEqual(status,200)
            if result['state']=='done':return result['result']
            time.sleep(.01)
        self.fail('Job failed to complete')

    def test_search_missing_ai_and_history_clear(self):
        headers=self.session()
        status,_,accepted=self.post('/api/chat',{'text':'/search ESP32','mode':'chat'},headers)
        self.assertEqual(status,202)
        outcome=self.finish(accepted['job'],headers)
        self.assertTrue(outcome['results'])
        self.assertIn('no AI reasoning',outcome['engine'])
        status,_,session=self.request('/api/session',headers=headers)
        self.assertEqual(len(session['history']),2)
        status,_,accepted=self.post('/api/chat',{'text':'Hello','mode':'chat'},headers)
        self.assertFalse(self.finish(accepted['job'],headers)['ok'])
        self.assertEqual(self.post('/api/clear',{},headers)[0],200)
        self.assertEqual(self.request('/api/session',headers=headers)[2]['history'],[])

    def test_csrf_origin_schema_and_body_size(self):
        headers=self.session();payload={'text':'/help','mode':'chat'}
        bad=dict(headers);bad.pop('X-Jarvis-CSRF')
        self.assertEqual(self.post('/api/chat',payload,bad)[0],403)
        bad=dict(headers);bad['Origin']='https://evil.example'
        self.assertEqual(self.post('/api/chat',payload,bad)[0],403)
        bad=dict(headers);bad['Content-Type']='text/plain'
        self.assertEqual(self.post('/api/chat',payload,bad)[0],415)
        for value in [{},[],{'text':'','mode':'chat'},{'text':'x','mode':'shell'}, {'text':'x','mode':[]}, {'text':'x','mode':'chat','approved':True}]:
            self.assertEqual(self.post('/api/chat',value,headers)[0],400)
        self.assertEqual(self.request('/api/chat','x'*20001,headers)[0],413)
        self.assertEqual(self.request('/api/chat','{bad json',headers)[0],400)

    def test_jobs_private_and_confirmations_cannot_be_forged(self):
        headers=self.session();other=self.session()
        status,_,accepted=self.post('/api/chat',{'text':'/app vscode','mode':'chat'},headers)
        self.assertEqual(self.request('/api/jobs/'+accepted['job'],headers=other)[0],404)
        outcome=self.finish(accepted['job'],headers)
        token=outcome['confirmation']['token']
        status,_,job=self.post('/api/confirm',{'token':token,'approved':True},other)
        self.assertFalse(self.finish(job['job'],other)['ok'])
        status,_,job=self.post('/api/confirm',{'token':token,'approved':False},headers)
        self.assertIn('Cancelled',self.finish(job['job'],headers)['spoken'])

    def test_plan_only_contains_supplied_tasks(self):
        headers=self.session()
        tasks=[{'text':'My actual school task','category':'school','urgent':True}]
        status,_,accepted=self.post('/api/plan',{'tasks':tasks},headers)
        self.assertEqual(status,202)
        self.assertEqual(self.finish(accepted['job'],headers)['priorities'],tasks)
        self.assertEqual(self.post('/api/plan',{'tasks':[]},headers)[0],400)

    def test_subject_modes_reach_assistant_without_schema_errors(self):
        headers=self.session()
        for mode in ['football','maths','science','geography','ict','coding']:
            status,_,accepted=self.post('/api/chat',{'text':'Explain this topic','mode':mode},headers)
            self.assertEqual(status,202)
            outcome=self.finish(accepted['job'],headers)
            self.assertIn('Ollama unavailable',outcome['spoken'])

    def test_model_selection_requires_csrf_and_strict_schema(self):
        headers=self.session()
        with patch.object(self.assistant.ai,'select_model',return_value='installed:test',create=True) as select:
            self.assertEqual(self.post('/api/model',{'model':'installed:test'},{'Content-Type':'application/json'})[0],403)
            for payload in [{'model':[]},{'model':'x','download':True},{'model':''}]:
                self.assertEqual(self.post('/api/model',payload,headers)[0],400)
            select.assert_not_called()
            status,_,accepted=self.post('/api/model',{'model':'installed:test'},headers)
            self.assertEqual(status,202)
            self.assertEqual(self.finish(accepted['job'],headers)['model'],'installed:test')
            select.assert_called_once_with('installed:test')

    def test_calculator_works_over_http_without_model(self):
        headers=self.session()
        status,_,accepted=self.post('/api/chat',{'text':'199 × 599','mode':'maths'},headers)
        self.assertEqual(status,202)
        outcome=self.finish(accepted['job'],headers)
        self.assertEqual(outcome['calculation']['result'],'119,201')
