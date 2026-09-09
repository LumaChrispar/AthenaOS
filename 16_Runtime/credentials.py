"""Store only Athena's own credential in the current user's OS credential vault."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path


def target_name(root=None):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    identity = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:24]
    return 'AthenaOS/OpenRouter/' + identity


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def windows_vault():
    dll = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


def other_vault():
    try:
        import keyring
        backend = keyring.get_keyring()
        if type(backend).__module__ not in ('keyring.backends.macOS', 'keyring.backends.SecretService', 'keyring.backends.libsecret'):
            raise RuntimeError('No supported OS credential vault is available.')
        return backend
    except ImportError:
        raise RuntimeError('Install the requirements to enable secure key storage.') from None


def read_key(root=None):
    if os.name != 'nt':
        return other_vault().get_password(target_name(root), 'openrouter')
    vault, pointer = windows_vault(), ctypes.POINTER(Credential)()
    if not vault.CredReadW(target_name(root), 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise RuntimeError('Windows Credential Manager is unavailable in this login session.')
    try:
        return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode('utf-16-le')
    finally:
        vault.CredFree(pointer)


def validate_key(key):
    if not isinstance(key, str) or not 16 <= len(key.strip()) <= 2048 or any(not 33 <= ord(c) <= 126 for c in key.strip()):
        raise ValueError('Paste the complete API key, without spaces or line breaks.')
    return key.strip()


def save_key(key, root=None):
    key = validate_key(key)
    if os.name != 'nt':
        other_vault().set_password(target_name(root), 'openrouter', key)
        return
    encoded = key.encode('utf-16-le')
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = Credential(Type=1, TargetName=target_name(root), UserName='openrouter',
                            CredentialBlobSize=len(encoded), CredentialBlob=blob, Persist=2)
    if not windows_vault().CredWriteW(ctypes.byref(credential), 0):
        raise RuntimeError('Could not save the key in Windows Credential Manager. Try running Athena from your normal desktop session.')


def delete_key(root=None):
    if os.name != 'nt':
        vault = other_vault()
        if vault.get_password(target_name(root), 'openrouter') is not None:
            vault.delete_password(target_name(root), 'openrouter')
        return
    if not windows_vault().CredDeleteW(target_name(root), 1, 0) and ctypes.get_last_error() != 1168:
        raise RuntimeError('Could not remove the saved key from Windows Credential Manager.')
