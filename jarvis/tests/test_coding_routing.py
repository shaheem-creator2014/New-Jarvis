"""Code-generation regressions use test doubles, not live model quality claims."""
import unittest
from unittest.mock import patch
from agent.ai import Ollama, coding_requested
from agent.conversation import Assistant
from agent.data import selected_source
from agent.vault import KnowledgeIndex


class CodingRoutingTests(unittest.TestCase):
    def test_code_requests_and_edits(self):
        for text in ['write a code', 'write a code code', 'write Python code to open GitHub',
                     'build a website', 'create an HTML page', 'explain this Python code',
                     'can you code a calculator', 'debug my script', '```python\nprint(1)\n```']:
            with self.subTest(text=text): self.assertTrue(coding_requested(text))
        history=[{'role':'user','content':'write Python code for a calculator'}]
        self.assertTrue(coding_requested('add multiplication',history))
        self.assertFalse(coding_requested('open GitHub',history))
        for text in ['open VS Code', 'open GitHub', 'What is gravity?', 'Find my robotics notes']:
            self.assertFalse(coding_requested(text))

    def test_conversation_coding_uses_answer_only_schema_and_larger_budget(self):
        client=Ollama()
        answer={'message':{'content':'{"response":"print(1)","action":"none","argument":""}'}}
        with patch.object(client,'_request',return_value=answer) as request:
            client.respond([], 'write Python code to open https://example.com',mode='chat')
        payload=request.call_args.args[1]
        self.assertEqual(payload['format']['properties']['action']['enum'],['none'])
        self.assertEqual(payload['options']['num_predict'],1536)

    def test_wrong_website_choice_recovers_without_validating_url(self):
        assistant=Assistant(KnowledgeIndex(selected_source()).build())
        _,session=assistant.session()
        replies=[{'response':'','action':'open_website','argument':'https://unapproved.example/'},
                 {'response':'```python\nprint("Hello")\n```','action':'none','argument':''}]
        with patch.object(assistant.ai,'respond',side_effect=replies) as ai, patch.object(assistant,'propose') as propose:
            outcome=assistant.process(session,'write a code','chat')
        propose.assert_not_called()
        self.assertTrue(outcome['ok'])
        self.assertIn('print("Hello")',outcome['spoken'])
        self.assertTrue(all(call.kwargs['mode']=='coding' for call in ai.call_args_list))
        self.assertFalse(session['pending'])

    def test_repeated_bad_choice_never_proposes_action(self):
        assistant=Assistant(KnowledgeIndex(selected_source()).build())
        _,session=assistant.session()
        with patch.object(assistant.ai,'respond',return_value={'response':'','action':'windows_control','argument':'vscode'}), patch.object(assistant,'propose') as propose:
            outcome=assistant.process(session,'build a website','chat')
        self.assertFalse(outcome['ok'])
        propose.assert_not_called()
        self.assertNotIn('Only approved HTTPS',outcome['spoken'])
