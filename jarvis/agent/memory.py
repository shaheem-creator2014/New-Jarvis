"""The sole module allowed to create/delete memory files. Text is always data."""
import json
import os
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from .data import memory_directory

LOCAL_TZ = timezone(timedelta(hours=5,minutes=30),'Asia/Colombo')
FILE_ID = re.compile(r'\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md\Z')
SECRET = re.compile(r'\b(passwords?|passphrases?|passcodes?|api[ _-]*keys?|access[ _-]*tokens?|refresh[ _-]*tokens?|client[ _-]*secrets?|private[ _-]*keys?|bearer\s+\S+)\b|\b(?:sk[-_]|gh[pousr]_)[A-Za-z0-9_-]{12,}|\bAIza[A-Za-z0-9_-]{20,}|-----BEGIN.*PRIVATE KEY-----|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',re.IGNORECASE)
SENSITIVE = re.compile(r'\b(address|phone|medical|diagnosis|health|passport|national id|bank account|religion|birthday|birth date|salary|income)\b',re.IGNORECASE)
HEADER = '# JARVIS approved memory\n'


class MemoryStore:
    def __init__(self, source):
        self.source = source
        self.root = memory_directory(source)
        self.lock = threading.RLock()

    def safe(self, path):
        for component in [path,*path.parents]:
            if component.is_symlink() or getattr(component,'is_junction',lambda:False)():
                raise PermissionError('Memory paths must not use symbolic links or junctions')

    def validate(self, fact, *, sensitive=False):
        if not isinstance(fact,str) or not 1<=len(fact.strip())<=1000 or any(ord(c)<32 and c not in '\n\t' for c in fact):
            raise ValueError('A memory fact must contain 1–1000 characters of text')
        if type(sensitive) is not bool:
            raise ValueError('Sensitive must be a boolean')
        if SECRET.search(fact) or re.search(r'(?=[A-Za-z0-9_+/=.-]{40,}\b)(?=[A-Za-z0-9_+/=.-]*[A-Za-z])(?=[A-Za-z0-9_+/=.-]*\d)[A-Za-z0-9_+/=.-]{40,}',fact):
            raise PermissionError('Passwords, API keys and authentication tokens must never be stored as memories. Use a private credential manager instead.')
        return fact.strip(), bool(sensitive or SENSITIVE.search(fact))

    def _path(self, identifier):
        if not isinstance(identifier,str) or len(identifier)>140 or not FILE_ID.fullmatch(identifier):
            raise ValueError('Invalid memory identifier')
        path = self.root / identifier
        self.safe(path)
        return path

    def _read(self, identifier):
        path = self._path(identifier)
        if not path.is_file() or path.stat().st_size>8192:
            raise ValueError('Memory is missing or exceeds the safe size limit')
        text = path.read_text(encoding='utf-8')
        if not text.startswith(HEADER):
            raise ValueError('This file was not created as an approved JARVIS memory')
        metadata_line, separator, fact = text[len(HEADER):].partition('\n\n## Fact\n')
        if not separator:
            raise ValueError('Invalid memory format')
        metadata = json.loads(metadata_line.removeprefix('Metadata: '))
        if not isinstance(metadata,dict) or not isinstance(metadata.get('created_at'),str):
            raise ValueError('Invalid memory metadata')
        fact, sensitive = self.validate(fact,sensitive=metadata.get('sensitive',False))
        if metadata.get('demo') is not self.source.demo or metadata.get('kind') not in {'fact','reminder'}:
            raise ValueError('Memory belongs to a different source or has an invalid type')
        return {'id':identifier,'fact':fact,'created_at':metadata['created_at'],'sensitive':sensitive,
                'kind':metadata['kind'],'demo':self.source.demo}

    def list(self, query='', *, kind=None):
        if not isinstance(query,str) or len(query)>300 or kind not in {None,'fact','reminder'}:
            raise ValueError('Invalid memory filter')
        with self.lock:
            self.safe(self.root)
            if not self.root.exists():
                return {'ok':True,'tool':'recall_memory','memories':[],'warnings':[],'demo':self.source.demo,'spoken':'No approved memories are stored here, Shaheem.'}
            rows,warnings = [],[]
            candidates = sorted((path.name for path in self.root.iterdir() if FILE_ID.fullmatch(path.name)),reverse=True)
            for identifier in candidates[:500]:
                try:
                    row = self._read(identifier)
                    if query.casefold() in row['fact'].casefold() and (kind is None or row['kind']==kind):
                        rows.append(row)
                except (OSError,ValueError,TypeError,KeyError,PermissionError):
                    warnings.append('Skipped an invalid or inaccessible memory: '+identifier)
            if len(candidates)>500:
                warnings.append('Only the newest 500 memory filenames were inspected.')
            return {'ok':True,'tool':'recall_memory','memories':rows,'warnings':warnings,'demo':self.source.demo,
                    'spoken':f'{len(rows)} approved memories found, Shaheem.'}

    def save(self, fact, *, approved=False, sensitive=False, sensitive_approved=False, kind='fact'):
        fact, sensitive = self.validate(fact,sensitive=sensitive)
        if approved is not True:
            raise PermissionError('Approve the exact fact before it can be saved')
        if sensitive and sensitive_approved is not True:
            raise PermissionError('This fact may contain sensitive personal details. Give separate explicit approval before saving it.')
        if kind not in {'fact','reminder'}:
            raise ValueError('Memory type must be fact or reminder')
        with self.lock:
            self.safe(self.root)
            self.root.mkdir(parents=True,exist_ok=True)
            created = datetime.now(LOCAL_TZ).isoformat(timespec='seconds')
            slug = '-'.join(re.findall(r'[a-z0-9]+',fact.casefold())[:6])[:55].strip('-') or 'fact'
            identifier = created[:10]+'-'+slug+'-'+secrets.token_hex(6)+'.md'
            path = self._path(identifier)
            metadata = {'created_at':created,'sensitive':sensitive,'kind':kind,'demo':self.source.demo}
            content = HEADER+'Metadata: '+json.dumps(metadata)+'\n\n## Fact\n'+fact+'\n'
            descriptor = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            row = self._read(identifier)
            if row['fact']!=fact:
                raise OSError('Memory write could not be verified')
            return {'ok':True,'tool':'remember','memory':row,'spoken':f'Saved exactly: “{fact}”, Shaheem.','demo':self.source.demo}

    def delete(self, identifier, *, approved=False):
        if approved is not True:
            raise PermissionError('Explicit approval is required to delete this memory')
        with self.lock:
            row = self._read(identifier)
            self._path(identifier).unlink()
            return {'ok':True,'tool':'delete_memory','deleted_id':identifier,'spoken':f'Deleted the stored fact: “{row["fact"]}”, Shaheem.','demo':self.source.demo}
