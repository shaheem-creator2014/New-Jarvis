import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from agent.ai import AIUnavailable, Ollama
from agent.conversation import Assistant, BusyError
from agent.data import selected_source
from agent.tools import plan_day, search_brain
from agent.vault import KnowledgeIndex
from agent.windows import approved_application, approved_website, launch_application, launch_website

class FakeAI:
    """Explicit test double; never presented as a working model."""
    model = 'test-double'
    def __init__(self, action='none', argument='', response='Test response, Shaheem.'):
        self.reply = {'action': action, 'argument': argument, 'response': response}
        self.calls = []
    def respond(self, history, text, mode='chat'):
        self.calls.append((history, text, mode))
        return self.reply
    def status(self):
        return {'connected': False, 'model_ready': False, 'model': self.model}

class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.index = KnowledgeIndex(selected_source()).build()
        self.fake = FakeAI()
        self.assistant = Assistant(self.index, self.fake)
        self.identifier, self.session = self.assistant.session()

    def test_context_keeps_ten_turns_and_followups(self):
        for i in range(12):
            self.assistant.process(self.session, f'turn {i}', 'chat')
        self.assertEqual(len(self.session['history']), 20)
        self.assistant.process(self.session, 'Why?', 'chat')
        history, text, mode = self.fake.calls[-1]
        self.assertEqual(text, 'Why?')
        self.assertEqual(len(history), 20)
        self.assertEqual(history[0]['content'], 'turn 2')
        self.assertEqual(mode, 'chat')

    def test_context_budget(self):
        for _ in range(10):
            self.session['history'].extend([{'role':'user','content':'u'*4000}, {'role':'assistant','content':'a'*6000}])
        history = self.assistant.history(self.session)
        self.assertLessEqual(sum(len(item['content']) for item in history), 24000)
        self.assertEqual(history[0]['role'], 'user')

    def test_context_isolation(self):
        self.assistant.process(self.session, 'private conversation', 'chat')
        _, other = self.assistant.session()
        self.assertEqual(self.assistant.history(other), [])

    def test_search_model_routing_uses_actual_citations(self):
        self.fake.reply.update(action='search_brain', argument='ESP32', response='not used')
        reply = self.assistant.process(self.session, 'Find my ESP32 notes', 'chat')
        self.assertTrue(reply['results'])
        self.assertIn(reply['results'][0]['filename'], self.index.documents)
        self.assertNotIn('not used', reply['spoken'])

    def test_general_question_cannot_be_replaced_by_file_search(self):
        replies = [
            {'action': 'search_brain', 'argument': 'CR7 total goals', 'response': ''},
            {'action': 'none', 'argument': '', 'response': 'A current total needs a dated public source, Shaheem.'}]
        with patch.object(self.fake, 'respond', side_effect=replies) as respond, patch('agent.conversation.search_brain') as search:
            outcome = self.assistant.process(self.session, 'CR7 total goals', 'chat')
        search.assert_not_called()
        self.assertEqual(outcome['tool'], 'chat')
        self.assertIn('dated public source', outcome['spoken'])
        self.assertEqual(respond.call_args.kwargs['mode'], 'answer')

    def test_general_question_repeated_bad_routing_does_not_search(self):
        self.fake.reply.update(action='search_brain', argument='gravity')
        with patch('agent.conversation.search_brain') as search:
            outcome = self.assistant.process(self.session, 'What is gravity?', 'chat')
        search.assert_not_called()
        self.assertFalse(outcome['ok'])

    def test_open_requires_confirmation_then_single_use(self):
        self.fake.reply.update(action='windows_control', argument='vscode', response='Opened!')
        with patch('agent.conversation.execute_action', return_value={'spoken':'Test launch accepted', 'ok':True}) as launch:
            reply = self.assistant.process(self.session, 'Open VS Code', 'chat')
            launch.assert_not_called()
            self.assertNotIn('Opened!', reply['spoken'])
            token = reply['confirmation']['token']
            self.assistant.confirm(self.session, token, True)
            launch.assert_called_once_with('windows_control', 'vscode')
            with self.assertRaises(ValueError):
                self.assistant.confirm(self.session, token, True)

    def test_confirmation_cancel_expiry_and_session_binding(self):
        with patch('agent.conversation.execute_action') as execute:
            reply = self.assistant.propose(self.session, 'open_website', 'github')
            token = reply['confirmation']['token']
            _, other = self.assistant.session()
            with self.assertRaises(ValueError):
                self.assistant.confirm(other, token, True)
            self.assistant.confirm(self.session, token, False)
            token = self.assistant.propose(self.session, 'open_website', 'github')['confirmation']['token']
            self.session['pending'][token]['expires'] = time.monotonic() - 1
            with self.assertRaises(ValueError):
                self.assistant.confirm(self.session, token, True)
            execute.assert_not_called()

    def test_missing_ollama_has_honest_limited_mode(self):
        with patch.object(self.fake, 'respond', side_effect=AIUnavailable('Ollama unavailable')):
            reply = self.assistant.process(self.session, 'Hello', 'chat')
            self.assertFalse(reply['ok'])
            self.assertIn('Limited mode', reply['engine'])
            self.assertTrue(self.assistant.process(self.session, '/search ESP32', 'chat')['results'])
            self.assertIn('no AI reasoning', self.assistant.process(self.session, '/help', 'chat')['engine'])

    def test_invalid_app_cannot_be_proposed(self):
        with self.assertRaises(ValueError):
            self.assistant.propose(self.session, 'windows_control', 'powershell')
        self.assertFalse(self.session['pending'])

    def test_robotics_mode_forwarded_without_hardware(self):
        self.assistant.process(self.session, 'Explain an ESP32 pull-up resistor', 'robotics')
        self.assertEqual(self.fake.calls[-1][2], 'robotics')

    def test_single_worker_and_bounded_job(self):
        started, release = threading.Event(), threading.Event()
        def slow():
            started.set();release.wait(2)
            return {'ok':True,'spoken':'done'}
        job = self.assistant.submit(self.identifier, self.session, slow)
        self.assertTrue(started.wait(1))
        with self.assertRaises(BusyError):
            self.assistant.submit(self.identifier, self.session, slow)
        release.set()
        for _ in range(100):
            if self.assistant.jobs[job]['state']=='done':break
            time.sleep(.01)
        self.assertEqual(self.assistant.jobs[job]['result']['spoken'],'done')

class ToolTests(unittest.TestCase):
    def test_website_allowlist(self):
        self.assertEqual(approved_website('github'), 'https://github.com/')
        for value in ['file:///etc/passwd','javascript:alert(1)','http://github.com','https://github.com.evil.test','https://user@github.com','https://github.com/private','https://localhost/','https://github.com/?token=x','https://github.com/#x','https://github.com:bad/']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                approved_website(value)

    def test_app_allowlist(self):
        self.assertEqual(approved_application('vscode'), 'vscode')
        for value in ['cmd','powershell','vscode --install-extension x','notepad & calc','../calc.exe','python']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                approved_application(value)

    def test_platform_failure_never_claims_success(self):
        with patch('agent.windows.os.name','posix'), patch('agent.windows.subprocess.Popen') as process, patch('agent.windows.webbrowser.open') as browser:
            self.assertFalse(launch_application('vscode')['ok'])
            self.assertFalse(launch_website('github')['ok'])
            process.assert_not_called();browser.assert_not_called()

    def test_browser_rejection_is_failure(self):
        with patch('agent.windows.os.name','nt'), patch('agent.windows.webbrowser.open', return_value=False):
            self.assertFalse(launch_website('github')['ok'])

    def test_plan_preserves_tasks_caps_five_prioritizes_urgency(self):
        tasks=[{'text':f'Supplied task {i}', 'category':category, 'urgent':i==4} for i,category in enumerate(['content','website','school','robotics','other','commitment'])]
        outcome=plan_day(tasks)
        self.assertEqual(len(outcome['priorities']),5)
        self.assertEqual(outcome['priorities'][0]['text'],'Supplied task 4')
        self.assertEqual(outcome['priorities'][1]['text'],'Supplied task 2')
        self.assertTrue(all(item in tasks for item in outcome['priorities']))
        for invalid in [[],[{'text':'invent','category':'school'}], [{'text':'','category':'school','urgent':False}]]:
            with self.assertRaises(ValueError):plan_day(invalid)

class OllamaTransportTests(unittest.TestCase):
    """Real HTTP protocol exercise against a labeled local test server, not real inference."""
    @classmethod
    def setUpClass(cls):
        cls.requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data={'models':[{'name':'llama3.2:1b'}]}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                cls.requests.append(body)
                data={'message':{'content':json.dumps({'response':'Protocol test only','action':'none','argument':''})}}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_protocol_and_history_payload(self):
        client=Ollama();client.base=f'http://127.0.0.1:{self.server.server_port}'
        self.assertTrue(client.status()['model_ready'])
        response=client.respond([{'role':'user','content':'Earlier topic'}], 'Why?')
        self.assertEqual(response['response'],'Protocol test only')
        self.assertEqual(self.requests[-1]['messages'][-2]['content'],'Earlier topic')
        self.assertFalse(self.requests[-1]['stream'])
        self.assertEqual(self.requests[-1]['format']['properties']['action']['enum'][0], 'none')
        self.assertEqual(self.requests[-1]['options']['num_ctx'], 4096)
        self.assertEqual(self.requests[-1]['model'],'llama3.2:1b')

    def test_general_and_local_questions_have_distinct_tool_scopes(self):
        client=Ollama();client.base=f'http://127.0.0.1:{self.server.server_port}'
        for question in ['CR7 total goals', 'What is gravity?', 'Explain Python loops', '1+1?']:
            client.respond([], question)
            self.assertNotIn('search_brain', self.requests[-1]['format']['properties']['action']['enum'])
        client.respond([], 'Find my ESP32 notes')
        self.assertIn('search_brain', self.requests[-1]['format']['properties']['action']['enum'])
        client.respond([], 'CR7 total goals', mode='answer')
        self.assertEqual(self.requests[-1]['format']['properties']['action']['enum'], ['none'])

    def test_unavailable_and_invalid_output(self):
        client=Ollama()
        with patch.object(client,'_request',side_effect=AIUnavailable('Unavailable')):
            self.assertFalse(client.status()['connected'])
        for text in ['not JSON', '{}', '{"response":"ok","action":"shell","argument":"cmd"}']:
            with patch.object(client,'_request',return_value={'message':{'content':text}}), self.assertRaises(AIUnavailable):
                client.respond([], 'Hello')

class OllamaErrorTests(unittest.TestCase):
    def test_timeout_is_distinct_from_bad_json(self):
        client = Ollama()
        with patch.object(client.opener, 'open', side_effect=TimeoutError()):
            with self.assertRaisesRegex(AIUnavailable, 'too long'):
                client.respond([], 'Hello')
        with patch.object(client.opener, 'open') as opened:
            opened.return_value.__enter__.return_value.read.return_value = b'bad json'
            with self.assertRaisesRegex(AIUnavailable, 'invalid JSON'):
                client.respond([], 'Hello')
