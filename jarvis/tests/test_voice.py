"""Voice protocol/error tests use test doubles only; no paid provider calls."""
import base64
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from agent.voice import ElevenLabs, MAX_AUDIO_BYTES, VoiceError, decode_recording, speech_text
from agent.conversation import Assistant
from agent.data import selected_source
from agent.vault import KnowledgeIndex

WEBM = b'\x1aE\xdf\xa3' + b'test-only-audio-container' * 4

class VoiceTests(unittest.TestCase):
    def configured(self, demo=False):
        with patch.dict(os.environ, {'ELEVENLABS_API_KEY':'test-placeholder-not-a-key', 'ELEVENLABS_VOICE_ID':'test_voice'}):
            return ElevenLabs(demo=demo)

    def test_missing_key_and_voice_id(self):
        with patch.dict(os.environ, {}, clear=True):
            client = ElevenLabs(demo=False)
        self.assertFalse(client.status()['key_configured'])
        with self.assertRaises(VoiceError) as error: client.transcribe(WEBM,'audio/webm',approved=True)
        self.assertEqual(error.exception.code,'missing_key')
        client = self.configured();client.voice_id=''
        with self.assertRaises(VoiceError) as error:client.speak('Hello',approved=True)
        self.assertEqual(error.exception.code,'missing_voice')

    def test_no_request_without_approval_or_in_demo(self):
        for demo,approved,code in [(False,False,'approval_required'),(False,1,'approval_required'),(True,True,'demo_blocked')]:
            client=self.configured(demo)
            with patch.object(client,'_request') as request:
                with self.assertRaises(VoiceError) as error:client.transcribe(WEBM,'audio/webm',approved=approved)
                self.assertEqual(error.exception.code,code)
                request.assert_not_called()

    def test_recording_validation(self):
        encoded=base64.b64encode(WEBM).decode()
        self.assertEqual(decode_recording(encoded,'audio/webm;codecs=opus'),(WEBM,'audio/webm'))
        for encoded,mime in [('!!','audio/webm'),(encoded,'text/plain'),(base64.b64encode(b'bad format'*5).decode(),'audio/webm'),('', 'audio/webm')]:
            with self.subTest(mime=mime),self.assertRaises(ValueError):decode_recording(encoded,mime)
        with self.assertRaises(ValueError):decode_recording('x'*(MAX_AUDIO_BYTES*4//3+8),'audio/webm')

    def test_scribe_multipart_uses_fixed_fields_and_real_transcript(self):
        client=self.configured()
        with patch.object(client,'_request',return_value=json.dumps({'text':'Find my robotics notes'}).encode()) as request:
            outcome=client.transcribe(WEBM,'audio/webm',approved=True)
        self.assertEqual(outcome['transcript'],'Find my robotics notes')
        self.assertTrue(client.status()['verified_connection'])
        path,body,mime=request.call_args.args
        self.assertEqual(path,'/v1/speech-to-text')
        self.assertIn(b'scribe_v1',body)
        self.assertIn(b'name="file"; filename="recording.webm"',body)
        self.assertIn(WEBM,body)
        self.assertTrue(mime.startswith('multipart/form-data; boundary='))

    def test_empty_or_invalid_transcript_fails(self):
        client=self.configured()
        for response in [b'not JSON',b'{"text":""}',b'{"text":5}',b'{}']:
            with patch.object(client,'_request',return_value=response),self.assertRaises(VoiceError) as error:
                client.transcribe(WEBM,'audio/webm',approved=True)
            self.assertEqual(error.exception.code,'transcription')

    def test_speech_request_and_audio_validation(self):
        client=self.configured();mp3=b'ID3'+b'fixture-audio'
        with patch.object(client,'_request',return_value=mp3) as request:
            outcome=client.speak('Hello, Shaheem.',approved=True)
        self.assertEqual(base64.b64decode(outcome['audio']),mp3)
        path,body,mime=request.call_args.args
        self.assertEqual(path,'/v1/text-to-speech/test_voice?output_format=mp3_44100_128')
        self.assertEqual(json.loads(body)['text'],'Hello, Shaheem.')
        with patch.object(client,'_request',return_value=b'{"error":"not audio"}'),self.assertRaises(VoiceError):
            client.speak('Hello',approved=True)

    def test_long_answers_use_short_notice(self):
        self.assertIn('detailed answer',speech_text({'spoken':'x'*600}))
        self.assertIn('detailed answer',speech_text({'spoken':'Example:\n```python\nprint(1)\n```'}))
        self.assertEqual(speech_text({'spoken':'Two matching notes, Shaheem.'}),'Two matching notes, Shaheem.')

    def test_provider_errors_are_sanitized_and_not_retried(self):
        for code,detail,expected in [(401,{},'authentication'),(403,{},'authentication'),(402,{},'credits'),(401,{'status':'quota_exceeded'},'credits'),(429,{},'rate_limit'),(422,{},'invalid_request'),(500,{},'provider')]:
            client=self.configured();client.opener=MagicMock()
            body=json.dumps({'detail':detail,'sensitive':'DO NOT EXPOSE PROVIDER BODY'}).encode()
            client.opener.open.side_effect=urllib.error.HTTPError('https://api.elevenlabs.io',code,'test',{},io.BytesIO(body))
            with self.subTest(code=code),self.assertRaises(VoiceError) as error:
                client._request('/v1/speech-to-text',b'test','application/json',limit=1000)
            self.assertEqual(error.exception.code,expected)
            self.assertEqual(client.status()['last_request'],'error')
            self.assertNotIn('DO NOT EXPOSE',str(error.exception))
            client.opener.open.assert_called_once()

    def test_network_failure_and_oversized_response(self):
        client=self.configured();client.opener=MagicMock()
        client.opener.open.side_effect=urllib.error.URLError('network unavailable')
        with self.assertRaises(VoiceError) as error:client._request('/v1/speech-to-text',b'test','application/json',limit=100)
        self.assertEqual(error.exception.code,'network')
        client.opener.open.side_effect=None
        client.opener.open.return_value.__enter__.return_value.read.return_value=b'x'*101
        with self.assertRaises(VoiceError) as error:client._request('/v1/speech-to-text',b'test','application/json',limit=100)
        self.assertEqual(error.exception.code,'response_too_large')

    def test_status_never_exposes_secrets_or_claims_connection(self):
        client=self.configured();data=client.status()
        self.assertNotIn(client.key,json.dumps(data));self.assertNotIn(client.voice_id,json.dumps(data))
        self.assertFalse(data['verified_connection'])

    def test_speech_source_must_belong_to_session(self):
        assistant=Assistant(KnowledgeIndex(selected_source()).build(),voice=self.configured())
        identifier,session=assistant.session()
        assistant.jobs['sample']={'session':identifier,'state':'done','created':0,'result':{'spoken':'Actual completed response','tool':'chat'}}
        with patch.object(assistant.voice,'speak',return_value={'ok':True}) as request:
            with self.assertRaises(ValueError):assistant.speak('other-session','sample',True)
            request.assert_not_called()
            assistant.speak(identifier,'sample',True)
            request.assert_called_once_with('Actual completed response',approved=True)
