"""The sole configuration boundary for selecting demo versus approved data."""
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class DataSource:
    root: Path
    demo: bool

def selected_source(*, approve_real=False):
    mode = os.environ.get("JARVIS_DEMO", "1")
    if mode not in {"0", "1"}:
        raise ValueError("JARVIS_DEMO must be 0 or 1")
    if mode == "1":
        return DataSource(PROJECT / "data" / "demo", True)
    if not approve_real:
        raise PermissionError("Real document access requires --approve-real-knowledge")
    return DataSource(Path.home() / "Documents" / "JARVIS_KNOWLEDGE", False)


def integration_demo(source, *, now):
    """Fictional fixtures are selected only through this module."""
    if not source.demo:
        raise PermissionError('Fictional integration fixtures require demo mode')
    date = now.date().isoformat()
    return {
        'emails': [{'sender': 'Demo Alex <alex@example.invalid>', 'subject': 'Fictional robotics workshop',
                    'excerpt': 'FICTIONAL DEMO: sample workshop notes are ready. This is not a real email.',
                    'sender_evidence': []}],
        'events': [{'title': 'FICTIONAL DEMO — sample study session', 'start': date + 'T16:00:00+05:30',
                    'end': date + 'T17:00:00+05:30'}],
        'tasks': [{'text': 'FICTIONAL DEMO — review sample robotics notes', 'category': 'robotics', 'urgent': False}],
        'reminders': ['FICTIONAL DEMO — bring a notebook to the sample session.'],
    }


def memory_directory(source):
    return PROJECT / 'memory' / 'demo' if source.demo else PROJECT / 'memory'


def load_configuration(path=None):
    """Load only supported server settings; process environment wins. No evaluation."""
    import re
    path = Path(path) if path is not None else PROJECT / '.env'
    if not path.exists():
        return
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Local .env must be a regular file no larger than 64 KB')
    allowed = {'JARVIS_DEMO','JARVIS_MODEL','ELEVENLABS_API_KEY','ELEVENLABS_VOICE_ID',
               'JARVIS_SEARCH_PROVIDER','BRAVE_SEARCH_API_KEY','JARVIS_GOOGLE_CLIENT_ID','JARVIS_GOOGLE_CLIENT_SECRET'}
    settings = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name) or name not in allowed or '\x00' in value:
            raise ValueError(f'Invalid or unsupported .env setting on line {number}; values are never evaluated')
        if value.startswith(('"',"'")):
            if len(value)<2 or value[-1]!=value[0]:
                raise ValueError(f'Unclosed .env quote on line {number}')
            value = value[1:-1]
        settings[name] = value
    for name,value in settings.items():
        os.environ.setdefault(name,value)
