"""Optional existing Playwright/Chromium check. UI doubles are not real AI validation."""
import threading
from playwright.sync_api import sync_playwright, expect
from agent.conversation import Assistant
from agent.data import selected_source
from agent.server import make_server
from agent.vault import KnowledgeIndex


class UIOnlyAI:
    model = 'ui-test:small'
    def __init__(self): self.calls = []
    def status(self):
        return {'connected': True, 'model_ready': True, 'model': self.model,
                'message': 'UI TEST DOUBLE', 'models': ['ui-test:small', 'ui-test:larger']}
    def select_model(self, name):
        if name not in self.status()['models']: raise ValueError('Not installed')
        self.model = name
        return name
    def respond(self, history, text, mode='chat'):
        self.calls.append((text, mode))
        return {'response': 'UI TEST DOUBLE ONLY\n```python\nprint("<img src=x onerror=alert(1)>")\n```',
                'action': 'none', 'argument': ''}


def main():
    index = KnowledgeIndex(selected_source()).build()
    ai = UIOnlyAI()
    server = make_server(index, port=0, assistant=Assistant(index, ai))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1366, 'height': 900})
            errors=[]
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('#chat-mode').select_option('maths')
            page.locator('#command').fill('199 × 599')
            page.locator('#command').press('Enter')
            expect(page.locator('#history')).to_contain_text('119,201', timeout=10000)
            assert not ai.calls
            page.locator('#chat-mode').select_option('coding')
            page.locator('#command').fill('Explain this:')
            page.locator('#command').press('Shift+Enter')
            page.locator('#command').type('print(1)')
            assert '\n' in page.locator('#command').input_value()
            page.locator('#command').press('Enter')
            expect(page.locator('#history pre code')).to_contain_text('<img src=x onerror=alert(1)>')
            assert ai.calls[-1] == ('Explain this:\nprint(1)', 'coding')
            assert page.locator('#history img').count() == 0
            expect(page.locator('#send')).to_be_enabled()
            page.locator('#model-open').click()
            expect(page.locator('#model-choice option')).to_have_count(2)
            page.locator('#model-choice').select_option('ui-test:larger')
            page.locator('#model-apply').click()
            expect(page.locator('#history')).to_contain_text('Using ui-test:larger', timeout=10000)
            assert ai.model == 'ui-test:larger'
            for width,height in [(1887,950),(1366,768),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                page.wait_for_timeout(150)
                graph=page.locator('.graph-stage').bounding_box()
                chat=page.locator('.command-center').bounding_box()
                assert graph['y']+graph['height'] <= chat['y']
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
            print('PASS: calculator, subject mode, multiline/code safety, installed-model selection, responsive layout. AI was a UI test double.')
    finally:
        server.shutdown();server.server_close();thread.join()


if __name__ == '__main__': main()
