"""Server-only ElevenLabs requests. Explicit approval, fixed HTTPS host, no disk audio."""
import base64
import binascii
import json
import os
import re
import secrets
import urllib.error
import urllib.request

MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_SPEECH_BYTES = 2 * 1024 * 1024
MAX_SPEECH_CHARACTERS = 500
MIME_TYPES = {'audio/webm': ('webm', b'\x1aE\xdf\xa3'),
              'audio/ogg': ('ogg', b'OggS'), 'audio/mp4': ('mp4', None)}

class VoiceError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VoiceError('network', 'ElevenLabs redirected the request; it was stopped to protect credentials.')


def decode_recording(encoded, mime):
    if not isinstance(encoded, str) or len(encoded) > (MAX_AUDIO_BYTES * 4 // 3 + 4):
        raise ValueError('Recording exceeds the 6 MB limit')
    if not isinstance(mime, str):
        raise ValueError('Missing audio format')
    mime = mime.split(';', 1)[0].lower()
    if mime not in MIME_TYPES:
        raise ValueError('Supported recording formats: WebM, Ogg or MP4')
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError('Invalid recording encoding') from error
    if not 16 <= len(audio) <= MAX_AUDIO_BYTES:
        raise ValueError('Recording is empty, too short or too large')
    signature = MIME_TYPES[mime][1]
    if (signature and not audio.startswith(signature)) or (mime == 'audio/mp4' and audio[4:8] != b'ftyp'):
        raise ValueError('Recording format does not match its content')
    return audio, mime


def speech_text(outcome):
    text = outcome.get('spoken', '')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('There is no response to speak')
    if len(text) > MAX_SPEECH_CHARACTERS or '```' in text:
        return 'I have put the detailed answer in the conversation, Shaheem. Please review it there.'
    return text.strip()

class ElevenLabs:
    def __init__(self, *, demo=True):
        self.demo = demo
        self.key = os.environ.get('ELEVENLABS_API_KEY', '')
        self.voice_id = os.environ.get('ELEVENLABS_VOICE_ID', '')
        self.opener = urllib.request.build_opener(NoRedirect())
        self.last_result = None

    def status(self):
        configured_voice = bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.voice_id))
        return {'key_configured': bool(self.key), 'voice_configured': configured_voice,
                'demo_blocked': self.demo, 'verified_connection': self.last_result == 'success', 'last_request': self.last_result,
                'message': 'External voice calls are blocked in demo mode.' if self.demo else
                           'Last provider request succeeded; further requests still require approval.' if self.last_result == 'success' else
                           'Last provider request failed; text chat remains available.' if self.last_result == 'error' else
                           'Key configured; connection not tested.' if self.key else 'ElevenLabs key is missing. Text chat remains available.'}

    def authorize(self, approved, *, tts=False):
        if approved is not True:
            raise VoiceError('approval_required', 'Explicit approval is required: even free-tier ElevenLabs requests consume account credits.')
        if self.demo:
            raise VoiceError('demo_blocked', 'ElevenLabs calls are blocked in demo mode. Local microphone testing and text chat remain available.')
        if not self.key:
            raise VoiceError('missing_key', 'ElevenLabs API key is not configured on the Python server. Text chat remains available.')
        if tts and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.voice_id):
            raise VoiceError('missing_voice', 'Set ELEVENLABS_VOICE_ID on the Python server before requesting speech.')

    def _request(self, path, body, content_type, *, limit):
        request = urllib.request.Request('https://api.elevenlabs.io' + path, data=body,
            headers={'xi-api-key': self.key, 'Content-Type': content_type}, method='POST')
        try:
            with self.opener.open(request, timeout=45) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise VoiceError('response_too_large', 'ElevenLabs returned too much data. No automatic retry was made; the request may have used credits.')
            return raw
        except urllib.error.HTTPError as error:
            self.last_result = 'error'
            # Inspect only the bounded machine-readable status; never return provider bodies or secrets.
            status = ''
            try:
                detail = json.loads(error.read(16000)).get('detail', {})
                if isinstance(detail, dict):
                    value = detail.get('status', '')
                    status = value if isinstance(value, str) else ''
            except (ValueError, OSError, AttributeError):
                pass
            if status in {'quota_exceeded', 'insufficient_credits', 'insufficient_funds'} or error.code == 402:
                raise VoiceError('credits', 'ElevenLabs credits are exhausted or billing approval is required. Check your account; text chat still works.') from error
            if error.code in {401, 403}:
                raise VoiceError('authentication', 'ElevenLabs rejected the key or its permissions. Check the server configuration; text chat still works.') from error
            if error.code == 429:
                raise VoiceError('rate_limit', 'ElevenLabs is rate-limiting requests. Wait before manually retrying; no automatic retry was made.') from error
            if error.code in {400, 422}:
                raise VoiceError('invalid_request', 'ElevenLabs rejected the audio or voice configuration. Check the format and voice ID.') from error
            raise VoiceError('provider', f'ElevenLabs returned HTTP {error.code}. No successful result is claimed.') from error
        except VoiceError:
            self.last_result = 'error'
            raise
        except (OSError, TimeoutError) as error:
            self.last_result = 'error'
            raise VoiceError('network', 'The ElevenLabs request failed or timed out. It may have consumed credits; no automatic retry was made.') from error

    def transcribe(self, audio, mime, *, approved=False):
        self.authorize(approved)
        # Revalidate at this boundary as well as at the HTTP endpoint.
        audio, mime = decode_recording(base64.b64encode(audio).decode('ascii'), mime)
        boundary = 'jarvis-' + secrets.token_hex(16)
        fields = {'model_id': 'scribe_v1', 'tag_audio_events': 'false', 'diarize': 'false'}
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        extension = MIME_TYPES[mime][0]
        parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.{extension}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), audio,
                      f'\r\n--{boundary}--\r\n'.encode()])
        raw = self._request('/v1/speech-to-text', b''.join(parts), 'multipart/form-data; boundary=' + boundary, limit=512*1024)
        try:
            data = json.loads(raw)
            text = data['text']
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
                raise ValueError('No usable transcript')
        except (ValueError, KeyError, TypeError) as error:
            self.last_result = 'error'
            raise VoiceError('transcription', 'No usable speech transcript was returned. Try a shorter, clearer recording; another request needs approval.') from error
        self.last_result = 'success'
        return {'ok': True, 'tool': 'scribe', 'transcript': text.strip(), 'spoken': 'Transcription completed, Shaheem.', 'engine': 'ElevenLabs Scribe'}

    def speak(self, text, *, approved=False):
        self.authorize(approved, tts=True)
        if not isinstance(text, str) or not 1 <= len(text) <= MAX_SPEECH_CHARACTERS:
            raise ValueError('Speech text must contain 1–500 characters')
        body = json.dumps({'text': text, 'model_id': 'eleven_multilingual_v2'}).encode('utf-8')
        raw = self._request('/v1/text-to-speech/' + self.voice_id + '?output_format=mp3_44100_128', body, 'application/json', limit=MAX_SPEECH_BYTES)
        if not raw or not (raw.startswith(b'ID3') or (len(raw) >= 2 and raw[0] == 255 and raw[1] & 224 == 224)):
            self.last_result = 'error'
            raise VoiceError('speech', 'ElevenLabs returned invalid MP3 audio. Playback was not started.')
        self.last_result = 'success'
        return {'ok': True, 'tool': 'tts', 'spoken': 'Speech audio generated.', 'audio': base64.b64encode(raw).decode('ascii'), 'mime': 'audio/mpeg'}
