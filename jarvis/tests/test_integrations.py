"""Read-only integration tests. All OAuth/provider responses are explicit doubles."""
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from agent.credentials import TokenStore
from agent.data import DataSource, selected_source
from agent.integrations import Integrations, IntegrationError, LOCAL_TZ, SCOPES, safe_public_url
from agent.vault import KnowledgeIndex

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=DataSource(self.root,False)
        (self.root/'client.md').write_text('Owner-approved note mentions alex@example.invalid\n',encoding='utf-8')
        self.index=KnowledgeIndex(self.source).build()
        self.api=Integrations(self.index)
        self.api.store.root=self.root/'auth'
        self.api.client_id='test-desktop-client'
        self.api.client_secret='test-client-secret-not-real'

    def token(self,service='gmail',expires=3600):
        value={'access_token':'test-access-not-real','refresh_token':'test-refresh-not-real','scope':SCOPES[service],'expires_at':time.time()+expires}
        self.api.store.memory[service]=value
        return value

    def test_demo_isolation_and_brief_fixtures(self):
        demo=Integrations(KnowledgeIndex(selected_source()).build())
        with patch.object(demo,'_json') as network,patch.object(demo.store,'load') as load,patch.object(demo.store,'has') as has:
            self.assertTrue(demo.inbox()['demo'])
            self.assertTrue(demo.calendar()['demo'])
            brief=demo.brief()
            self.assertTrue(brief['demo'])
            self.assertIn('FICTIONAL',brief['sections']['events'][0]['title'])
            demo.status()
            for action in [lambda:demo.begin('gmail','session',8765,approved=True),lambda:demo.research('robotics',approved=True),lambda:demo.disconnect('gmail','session')]:
                with self.assertRaises(IntegrationError):action()
            network.assert_not_called();load.assert_not_called();has.assert_not_called()

    def test_oauth_separate_scope_pkce_and_state(self):
        begun=self.api.begin('gmail','owner-session',8765,approved=True)
        url=urllib.parse.urlsplit(begun['authorization_url']);params=urllib.parse.parse_qs(url.query)
        self.assertEqual(url.hostname,'accounts.google.com')
        self.assertEqual(params['scope'],[SCOPES['gmail']])
        self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertNotIn(self.api.client_secret,begun['authorization_url'])
        state=params['state'][0]
        self.assertEqual(self.api.pending[state]['session'],'owner-session')
        token={'access_token':'test-access','refresh_token':'test-refresh','token_type':'Bearer','expires_in':3600,'scope':SCOPES['gmail']}
        with patch.object(self.api,'_json',return_value=token) as request:
            self.assertEqual(self.api.finish({'state':[state],'code':['test-code']}),'gmail')
            self.assertIn('code_verifier',request.call_args.kwargs['form'])
            self.assertEqual(request.call_args.kwargs['form']['redirect_uri'],'http://127.0.0.1:8765/oauth/google/callback')
            with self.assertRaises(IntegrationError):self.api.finish({'state':[state],'code':['test-code']})
            request.assert_called_once()

    def test_oauth_denied_invalid_expired_and_no_approval(self):
        with self.assertRaises(IntegrationError):self.api.begin('gmail','s',8765,approved=False)
        for kind in ['invalid','expired','denied']:
            result=self.api.begin('calendar','s',8765,approved=True)
            state=urllib.parse.parse_qs(urllib.parse.urlsplit(result['authorization_url']).query)['state'][0]
            if kind=='expired':self.api.pending[state]['expires']=time.monotonic()-1
            params={'state':['not-the-state' if kind=='invalid' else state],'code':['test']}
            if kind=='denied':params={'state':[state],'error':['access_denied']}
            with patch.object(self.api,'_json') as request,self.assertRaises(IntegrationError):self.api.finish(params)
            request.assert_not_called()
        self.assertFalse(self.api.store.memory)

    def test_no_broad_scopes_and_invalid_tokens(self):
        for token in [{}, {'access_token':'x','token_type':'Bearer','scope':'https://mail.google.com/'}, {'access_token':'x','token_type':'Bearer','scope':SCOPES['gmail']+' '+SCOPES['calendar']}, {'access_token':'x','token_type':'Bearer','expires_in':-10}]:
            with self.assertRaises(IntegrationError):self.api.validate_token(token,'gmail')

    def test_refresh_and_disconnect(self):
        self.token(expires=-1)
        with patch.object(self.api,'_json',return_value={'access_token':'new-test-access','token_type':'Bearer','expires_in':3600,'scope':SCOPES['gmail']}) as request:
            self.assertEqual(self.api.access('gmail'),'new-test-access')
            self.assertEqual(request.call_args.kwargs['form']['grant_type'],'refresh_token')
            self.assertEqual(self.api.store.memory['gmail']['refresh_token'],'test-refresh-not-real')
        self.api.disconnect('gmail','s')
        self.assertFalse(self.api.store.has('gmail'))
        with self.assertRaises(IntegrationError):self.api.access('gmail')

    def test_gmail_readonly_bounded_excerpts_and_sender_citations(self):
        self.token()
        responses=[{'messages':[{'id':'abc123'}],'nextPageToken':'more'}, {'snippet':'Actual provider excerpt.','payload':{'headers':[{'name':'From','value':'Alex <alex@example.invalid>'},{'name':'Subject','value':'Actual subject'}]}}]
        with patch.object(self.api,'_json',side_effect=responses) as request:
            reply=self.api.inbox()
        self.assertTrue(reply['has_more'])
        self.assertEqual(reply['emails'][0]['subject'],'Actual subject')
        self.assertEqual(reply['emails'][0]['sender'],'Alex <alex@example.invalid>')
        self.assertEqual(reply['emails'][0]['sender_evidence'][0]['citation'],'client.md:1')
        for call in request.call_args_list:
            self.assertNotIn('form',call.kwargs)
            self.assertNotIn('/send',call.args[0]);self.assertNotIn('/modify',call.args[0])
        self.assertIn('format=metadata',request.call_args_list[1].args[0])
        self.assertNotIn('body',reply['emails'][0])

    def test_calendar_today_uses_colombo_day_boundaries(self):
        self.token('calendar')
        fixed=datetime(2026,10,24,0,15,tzinfo=LOCAL_TZ)
        response={'items':[{'summary':'Actual event','start':{'dateTime':'2026-10-24T09:00:00+05:30'},'end':{'dateTime':'2026-10-24T10:00:00+05:30'}}]}
        with patch.object(self.api,'now',return_value=fixed),patch.object(self.api,'_json',return_value=response) as request:
            outcome=self.api.calendar()
        params=urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[0]).query)
        self.assertEqual(params['timeMin'],['2026-10-24T00:00:00+05:30'])
        self.assertEqual(params['timeMax'],['2026-10-25T00:00:00+05:30'])
        self.assertEqual(params['timeZone'],['Asia/Colombo'])
        self.assertEqual(outcome['events'][0]['title'],'Actual event')
        self.assertNotIn('form',request.call_args.kwargs)

    def test_gmail_and_calendar_authorization_failures(self):
        for service,method in [('gmail',self.api.inbox),('calendar',self.api.calendar)]:
            with self.subTest(service=service),self.assertRaises(IntegrationError):method()
            self.token(service)
            with patch.object(self.api,'_json',side_effect=IntegrationError('authorization','Test authorization denied')),self.assertRaises(IntegrationError):method()
            self.assertEqual(self.api.last[service],'error')

    def test_brief_missing_sections_are_explicit(self):
        tasks=[{'text':'Actual task supplied','category':'school','urgent':True}]
        brief=self.api.brief(tasks)
        self.assertEqual(brief['sections']['tasks'],tasks)
        self.assertEqual(brief['sections']['events'],[])
        self.assertEqual(brief['sections']['emails'],[])
        self.assertTrue(any('Calendar' in text for text in brief['unavailable']))
        self.assertTrue(any('Gmail' in text for text in brief['unavailable']))
        self.assertTrue(any('Reminders' in text for text in brief['unavailable']))

    def test_search_config_approval_and_safe_citations(self):
        with self.assertRaises(IntegrationError):self.api.research('ESP32',approved=True)
        self.api.provider='wikipedia'
        with patch.object(self.api,'_json') as request,self.assertRaises(IntegrationError):self.api.research('ESP32',approved=False)
        request.assert_not_called()
        response={'query':{'pages':{'1':{'title':'ESP32','fullurl':'https://en.wikipedia.org/wiki/ESP32','extract':'Provider text.','index':1},'2':{'title':'Bad','fullurl':'javascript:alert(1)','extract':'Do not run'}}}}
        with patch.object(self.api,'_json',return_value=response):outcome=self.api.research('ESP32',approved=True)
        self.assertEqual(len(outcome['web_results']),1)
        self.assertEqual(outcome['web_results'][0]['excerpt'],'Provider text.')
        for value in ['file:///secret','javascript:alert(1)','http://example.org','https://user:pass@example.org','https://127.0.0.1/','https://machine.local/']:
            self.assertIsNone(safe_public_url(value))

    def test_brave_requires_key_and_explicit_approval(self):
        self.api.provider='brave';self.api.search_key=''
        with self.assertRaises(IntegrationError):self.api.research('ESP32',approved=True)
        self.api.search_key='test-key-not-real'
        with patch.object(self.api,'_json',return_value={'web':{'results':[{'title':'Source','url':'https://example.org/source','description':'Source excerpt'}]}}) as request:
            reply=self.api.research('ESP32',approved=True)
        self.assertEqual(reply['provider'],'brave')
        self.assertEqual(request.call_args.kwargs['headers'],{'X-Subscription-Token':'test-key-not-real'})

    def test_linux_tokens_memory_only_and_no_secret_in_status(self):
        with patch('agent.credentials.os.name','posix'):
            store=TokenStore();store.root=self.root/'private-test'
            store.save('gmail',{'access_token':'test-only-secret'})
            self.assertFalse(store.root.exists())
            self.assertEqual(store.load('gmail')['access_token'],'test-only-secret')
            store.delete('gmail');self.assertIsNone(store.load('gmail'))
        self.assertNotIn(self.api.client_secret,json.dumps(self.api.status()))
        self.assertNotIn('access_token',json.dumps(self.api.status()))
