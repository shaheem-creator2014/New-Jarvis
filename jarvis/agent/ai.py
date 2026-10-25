"""Bounded, local-only Ollama client. Never downloads models or runs tools."""
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .data import PROJECT

ACTIONS = ['none', 'search_brain', 'open_website', 'windows_control', 'plan_day',
           'read_inbox', 'google_calendar', 'brief_me', 'research_web', 'remember', 'recall_memory']
REPLY_SCHEMA = {'type': 'object', 'properties': {
    'response': {'type': 'string'}, 'action': {'type': 'string', 'enum': ACTIONS},
    'argument': {'type': 'string'}},
    'required': ['response', 'action', 'argument'], 'additionalProperties': False}

SUBJECTS = {
    'football': 'Explain football rules, tactics, players and historical tournaments. Distinguish career vs club vs international totals and official vs unofficial matches. Current goals, results, fixtures, injuries and transfers need dated public sources. Do not fabricate them.',
    'maths': 'Tutor mathematics with formulas, clear intermediate steps and a check of the result. Distinguish exact values from approximations and include units where relevant. Do not claim a calculation was tool-verified unless the server did it.',
    'science': 'Explain physics, chemistry and biology using accurate definitions, units, worked examples and assumptions. Distinguish established evidence from hypotheses; do not invent experiments or measurements.',
    'geography': 'Explain physical and human geography, countries, maps, climate and Sri Lankan geography. Distinguish countries, territories and regions, and qualify changing population or political data.',
    'ict': 'Teach ICT: hardware, operating systems, networking, databases, cybersecurity concepts, algorithms and digital literacy. Start with a simple definition and a concrete example. Do not claim alignment to a particular school syllabus unless supplied.',
    'coding': 'Help with Python, HTML, CSS, JavaScript, SQL, Arduino, ESP32 and MicroPython. Give usable code, name the language, explain the change, and include an example input/output where helpful. Ask for the error or relevant code if missing. Never claim code was executed or tested unless a tool result proves it. Do not install dependencies or execute code.',
    'robotics': 'Explain Arduino, ESP32, MicroPython, electronics and robotics clearly. Never upload firmware or operate hardware.',
}
CHAT_MODES = {'chat', 'search', *SUBJECTS}

MAX_RESPONSE_BYTES = 256 * 1024

def document_search_requested(text):
    """Restrict document retrieval to a stated local-source intent, not world facts."""
    return bool(re.search(r"\b(notes?|files?|documents?|indexed|knowledge base|knowledge folder|my code|my robotics code|my projects?)\b", text, re.I))

class AIUnavailable(RuntimeError):
    pass

class Ollama:
    def __init__(self, *, demo=True):
        self.demo = demo
        self.model = os.environ.get('JARVIS_MODEL', 'llama3.2:1b')
        self.base = 'http://127.0.0.1:11434'
        # This client can only address the loopback Ollama service, never remote hosts.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.prompt = (PROJECT / 'agent' / 'prompt.md').read_text(encoding='utf-8')

    def _request(self, path, payload=None, timeout=2):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(self.base + path, data=body,
                                         headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AIUnavailable('Ollama returned an oversized response; please shorten the request.')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError('Expected a JSON object')
            return result
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise AIUnavailable(f'Model {self.model} is unavailable. Install it in Ollama only with your approval.') from error
            raise AIUnavailable(f'Ollama returned HTTP {error.code}; check its server logs.') from error
        except (socket.timeout, TimeoutError) as error:
            raise AIUnavailable('Ollama took too long to reply. Close other heavy apps and try a shorter message. The model may still be loading; limited commands still work.') from error
        except ValueError as error:
            raise AIUnavailable('Ollama returned invalid JSON data. Check its server logs; no action was taken.') from error
        except OSError as error:
            raise AIUnavailable('Ollama is unavailable, timed out, or returned invalid data. Start Ollama and check the selected model. Limited commands still work.') from error

    def status(self):
        info = {'installed_cli': bool(shutil.which('ollama')), 'model': self.model,
                'connected': False, 'model_ready': False}
        try:
            result = self._request('/api/tags')
            models = result.get('models', [])
            if not isinstance(models, list):
                raise AIUnavailable('Ollama returned an invalid model list; check the local service.')
            names = {model.get('name') for model in models if isinstance(model, dict) and isinstance(model.get('name'), str)}
            info.update(connected=True, model_ready=self.model in names, models=sorted(name for name in names if len(name) <= 200 and not any(c.isspace() or ord(c) < 32 for c in name)))
            info['message'] = 'Ready' if info['model_ready'] else f'Missing model: {self.model}. No models downloaded.'
        except AIUnavailable as error:
            info['message'] = str(error)
        return info

    def select_model(self, name):
        if not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise ValueError('Choose an installed model from the list.')
        status = self.status()
        if not status['connected']:
            raise AIUnavailable(status['message'])
        if name not in status.get('models', []):
            raise ValueError('That model is not installed. No model was downloaded or selected.')
        self.model = name
        return name

    def respond(self, history, text, *, mode='chat'):
        instructions = self.prompt + ("\nCurrent source: FICTIONAL DEMO. Never treat these notes as real clients, events or commitments." if self.demo else "\nCurrent source: explicitly approved local knowledge. Only cited retrieved facts are known. Use account tools to discover their availability; never assume a connected account.")
        try:
            today = datetime.now(ZoneInfo('Asia/Colombo')).date().isoformat()
        except ZoneInfoNotFoundError:
            # Windows may lack IANA timezone data; Colombo is UTC+05:30.
            from datetime import timezone, timedelta
            today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
        instructions += f'\nToday in Sri Lanka: {today}. This date does not give you live news or statistics.'
        if mode in SUBJECTS:
            instructions += '\nSubject guidance: ' + SUBJECTS[mode] + '\nAnswer directly; return action=none. Ask a brief clarifying question only when essential.'
        schema = REPLY_SCHEMA
        if mode == 'answer' or mode in SUBJECTS:
            instructions += '\nAnswer the user directly using conversation and general knowledge. Do not call tools. If a fact needs current verification, say so briefly; never invent a current figure.'
            schema = {**REPLY_SCHEMA, 'properties': {**REPLY_SCHEMA['properties'],
                      'action': {'type': 'string', 'enum': ['none']}}}
        elif not document_search_requested(text):
            instructions += '\nThis message does not request local documents. Answer general questions directly; do not use search_brain. Current statistics require dated, verified public sources, not fictional demo notes.'
            schema = {**REPLY_SCHEMA, 'properties': {**REPLY_SCHEMA['properties'],
                      'action': {'type': 'string', 'enum': [a for a in ACTIONS if a != 'search_brain']}}}
        messages = [{'role': 'system' , 'content': instructions}, *history,
                    {'role': 'user', 'content': text}]
        result = self._request('/api/chat', {'model': self.model, 'messages': messages,
                    'stream': False, 'format': schema, 'keep_alive': '5m',
                    'options': {'num_ctx': 4096, 'num_predict': 1536 if mode == 'coding' else 768, 'temperature': 0.25}}, timeout=180)
        if result.get('done_reason') == 'length':
            raise AIUnavailable('The answer reached its length limit. Ask for one smaller part at a time; no incomplete tool action was accepted.')
        try:
            reply = json.loads(result['message']['content'])
            if not isinstance(reply, dict) or set(reply) - {'response', 'action', 'argument'}:
                raise ValueError('Unexpected response fields')
            response = reply.get('response', '')
            action = reply.get('action', 'none')
            argument = reply.get('argument', '')
            if not isinstance(response, str) or len(response) > 10000 or not isinstance(argument, str) or len(argument) > 300:
                raise ValueError('Invalid response fields')
            if action not in {'none', 'search_brain', 'open_website', 'windows_control', 'plan_day', 'read_inbox', 'google_calendar', 'brief_me', 'research_web', 'remember', 'recall_memory'}:
                raise ValueError('Unsupported action')
            if (mode == 'answer' or mode in SUBJECTS) and action != 'none':
                raise ValueError('Direct-answer responses cannot launch tools')
            if action == 'none' and not response.strip():
                raise ValueError('Empty response')
            return {'response': response, 'action': action, 'argument': argument}
        except (KeyError, TypeError, ValueError) as error:
            raise AIUnavailable('The local model returned an invalid structured answer. No action was taken; please try rephrasing.') from error
