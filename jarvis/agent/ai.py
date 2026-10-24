"""Bounded, local-only Ollama client. Never downloads models or runs tools."""
import json
import os
import shutil
import socket
import urllib.error
import urllib.request
from .data import PROJECT

MAX_RESPONSE_BYTES = 256 * 1024

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
        except (OSError, ValueError, socket.timeout) as error:
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
            info.update(connected=True, model_ready=self.model in names)
            info['message'] = 'Ready' if info['model_ready'] else f'Missing model: {self.model}. No models downloaded.'
        except AIUnavailable as error:
            info['message'] = str(error)
        return info

    def respond(self, history, text, *, mode='chat'):
        instructions = self.prompt + ("\nCurrent source: FICTIONAL DEMO. Never treat these notes as real clients, events or commitments." if self.demo else "\nCurrent source: explicitly approved local knowledge. Only cited retrieved facts are known. Use account tools to discover their availability; never assume a connected account.")
        if mode == 'robotics':
            instructions += '\nThis turn is robotics assistance: explain code and concepts. Return action=none. Never upload firmware or operate hardware.'
        messages = [{'role': 'system', 'content': instructions}, *history,
                    {'role': 'user', 'content': text}]
        result = self._request('/api/chat', {'model': self.model, 'messages': messages,
                    'stream': False, 'format': 'json', 'keep_alive': '5m',
                    'options': {'num_ctx': 8192, 'num_predict': 700, 'temperature': 0.25}}, timeout=90)
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
            if mode == 'robotics' and action != 'none':
                raise ValueError('Robotics responses cannot launch tools')
            if action == 'none' and not response.strip():
                raise ValueError('Empty response')
            return {'response': response, 'action': action, 'argument': argument}
        except (KeyError, TypeError, ValueError) as error:
            raise AIUnavailable('The local model returned an invalid structured answer. No action was taken; please try rephrasing.') from error
