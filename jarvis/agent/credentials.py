"""Owner-local OAuth storage: Windows DPAPI, memory only elsewhere."""
import ctypes
import json
import os
import secrets
from pathlib import Path
from ctypes import wintypes

SERVICES = {'gmail', 'calendar'}


def private_directory():
    return Path.home() / 'AppData' / 'Local' / 'JARVIS' / 'auth'


def dpapi(data, *, decrypt=False):
    if os.name != 'nt':
        raise OSError('DPAPI is only available on Windows')
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt32, kernel32 = ctypes.WinDLL('crypt32', use_last_error=True), ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows could not protect/unprotect the authorization token')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class TokenStore:
    def __init__(self):
        self.root = private_directory()
        self.memory = {}

    def path(self, service):
        if service not in SERVICES:
            raise ValueError('Unsupported Google service')
        return self.root / (service + '.dpapi')

    def safe_path(self, path):
        for component in [path, *path.parents]:
            if component.is_symlink() or getattr(component, 'is_junction', lambda: False)():
                raise OSError('Credential paths may not use symbolic links or junctions')

    def has(self, service):
        path = self.path(service)
        return service in self.memory or (os.name == 'nt' and path.is_file())

    def load(self, service):
        path = self.path(service)
        if service in self.memory:
            return dict(self.memory[service])
        if os.name != 'nt' or not path.is_file():
            return None
        self.safe_path(path)
        if path.stat().st_size > 65536:
            raise OSError('Stored authorization is invalid')
        value = json.loads(dpapi(path.read_bytes(), decrypt=True))
        if not isinstance(value, dict):
            raise OSError('Stored authorization is invalid')
        self.memory[service] = value
        return dict(value)

    def save(self, service, value):
        path = self.path(service)
        if os.name == 'nt':
            self.safe_path(path)
            self.root.mkdir(parents=True, exist_ok=True)
            encrypted = dpapi(json.dumps(value).encode('utf-8'))
            temporary = self.root / ('.token-' + secrets.token_hex(12))
            try:
                with temporary.open('xb') as stream:
                    stream.write(encrypted)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        self.memory[service] = dict(value)

    def delete(self, service):
        path = self.path(service)
        if os.name == 'nt':
            self.safe_path(path)
            path.unlink(missing_ok=True)
        self.memory.pop(service, None)
