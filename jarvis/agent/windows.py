"""Explicit desktop allowlists. No shells, URLs from models, or extra arguments."""
import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

WEBSITES = {'github': 'https://github.com/', 'youtube': 'https://www.youtube.com/',
            'vercel': 'https://vercel.com/', 'lovable': 'https://lovable.dev/'}
APPLICATIONS = {'vscode', 'calculator', 'notepad', 'explorer'}


def approved_website(value):
    if not isinstance(value, str):
        raise ValueError('Website must be an approved name or HTTPS homepage')
    candidate = WEBSITES.get(value.strip().lower(), value.strip())
    url = urlsplit(candidate)
    if (url.scheme != 'https' or url.username or url.password or url.port not in {None, 443}
            or url.query or url.fragment or url.path not in {'', '/'}):
        raise ValueError('Only approved HTTPS homepages are allowed: GitHub, YouTube, Vercel, Lovable')
    for approved in WEBSITES.values():
        if url.hostname == urlsplit(approved).hostname:
            return approved
    raise ValueError('Website is not on the allowlist')


def approved_application(value):
    if not isinstance(value, str) or value not in APPLICATIONS:
        raise ValueError('Approved apps: vscode, calculator, notepad, explorer')
    return value


def launch_application(name):
    approved_application(name)
    if os.name != 'nt':
        return {'ok': False, 'spoken': 'Windows controls require your Windows PC, Shaheem.', 'status': 'unsupported_platform'}
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    programs = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
    candidates = {
        'notepad': [windows / 'System32' / 'notepad.exe'],
        'calculator': [windows / 'System32' / 'calc.exe'],
        'explorer': [windows / 'explorer.exe'],
        'vscode': [local / 'Programs' / 'Microsoft VS Code' / 'Code.exe', programs / 'Microsoft VS Code' / 'Code.exe'],
    }[name]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        return {'ok': False, 'spoken': f'{name} was not found in its supported installation locations, Shaheem.', 'status': 'not_installed'}
    try:
        process = subprocess.Popen([str(executable)], shell=False, close_fds=True)
        try:
            code = process.wait(timeout=0.3)
        except subprocess.TimeoutExpired:
            code = None
        if code not in {None, 0}:
            raise OSError('Application process exited with an error')
        return {'ok': True, 'spoken': f'Windows accepted the launch of {name}, Shaheem. I cannot verify its window.',
                'status': 'launch_accepted', 'pid': process.pid}
    except OSError:
        return {'ok': False, 'spoken': f'Windows could not launch {name}, Shaheem.', 'status': 'launch_failed'}


def launch_website(value):
    url = approved_website(value)
    if os.name != 'nt':
        return {'ok': False, 'spoken': 'Website opening is available on your Windows PC, Shaheem; it was not opened in this cloud machine.', 'status': 'unsupported_platform', 'url': url}
    try:
        accepted = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        accepted = False
    return {'ok': bool(accepted), 'status': 'browser_accepted' if accepted else 'launch_failed',
            'spoken': 'Your browser accepted the website request, Shaheem. Page loading is not verified.' if accepted else 'The browser did not accept the website request, Shaheem.', 'url': url}
