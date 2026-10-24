"""Optional synthetic voice regression. Start JARVIS first; no provider calls.
Uses an existing Playwright/Chromium installation, never installs dependencies.
"""
import atexit
import math
import os
import shutil
import struct
import tempfile
import time
import wave
from pathlib import Path
try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    raise SystemExit('Optional browser check needs an existing Playwright installation. Nothing was installed.')
fixture_dir = tempfile.TemporaryDirectory(prefix='jarvis-synthetic-voice-')
atexit.register(fixture_dir.cleanup)
audio_path = Path(fixture_dir.name) / 'synthetic-tone.wav'
with wave.open(str(audio_path), 'wb') as audio:
    audio.setnchannels(1)
    audio.setsampwidth(2)
    audio.setframerate(48000)
    audio.writeframes(b''.join(struct.pack('<h', int(10000 * math.sin(2*math.pi*440*i/48000)) if i < 96000 else 0) for i in range(192000)))
browser_path = os.environ.get('JARVIS_TEST_BROWSER') or shutil.which('chromium') or shutil.which('chromium-browser')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=browser_path,headless=True,args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-audio-capture='+str(audio_path)])
    context=browser.new_context(permissions=['microphone'])
    page=context.new_page();received=[];ready=[float('inf')]
    def route(r):
        path=r.request.url.split('8765')[-1]
        if path=='/api/status':return r.fulfill(json={'ollama':{'model_ready':False,'connected':False,'message':'TEST FIXTURE'},'voice':{'demo_blocked':False,'key_configured':True,'voice_configured':True,'message':'TEST FIXTURE'}})
        if path=='/api/voice/transcribe':
            ready[0]=time.monotonic()+3
            return r.fulfill(status=202,json={'job':'late-test'})
        if path=='/api/jobs/late-test':
            return r.fulfill(json={'state':'running'} if time.monotonic()<ready[0] else {'state':'done','result':{'ok':True,'tool':'scribe','transcript':'/app vscode'}})
        if path in ['/api/chat','/api/voice/speak']:received.append(path)
        return r.continue_()
    page.route('**/api/**',route)
    page.goto('http://127.0.0.1:8765')
    expect(page.locator('#elevenlabs-state')).to_have_text('Key set · untested')
    page.locator('#microphone').click()
    expect(page.locator('#voice-consent')).to_be_visible(timeout=12000)
    page.locator('#voice-approve').click()
    expect(page.locator('#send')).to_be_disabled()
    page.keyboard.press('Escape')
    expect(page.locator('#voice-status')).to_contain_text('already-submitted')
    expect(page.locator('#send')).to_be_enabled(timeout=10000)
    expect(page.locator('#reactor')).to_have_attribute('data-state','idle')
    expect(page.locator('#mic-state')).to_have_text('Inactive')
    assert not received,received
    print('Late-result interruption check passed: delayed fixture transcript did not start chat, tools, speech or another recording; reactor returned to idle.')
    browser.close()
