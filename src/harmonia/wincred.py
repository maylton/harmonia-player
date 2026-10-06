"""Windows Credential Manager behind the libsecret calls used by secrets.py.

Each secret is a generic credential named after the schema and its attributes.
A credential blob holds at most 2560 bytes and a YouTube Music cookie header is
often longer, so values are split across numbered credentials: ``target``,
``target#1``, ``target#2``… A lookup reads them in order until one is missing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_MAX_BLOB_SIZE = 5 * 512
ERROR_NOT_FOUND = 1168
USER_NAME = "Harmonia"


class _FileTime(ctypes.Structure):
    _fields_ = (("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD))


class _Credential(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


def target_name(schema: str, attributes: dict[str, str]) -> str:
    """Name the credential after the schema and the attributes that tell entries apart."""
    parts = [value for key, value in sorted(attributes.items()) if key != "application"]
    return "/".join([schema, *parts])


def chunk_target(target: str, index: int) -> str:
    return target if index == 0 else f"{target}#{index}"


def split_blob(value: str) -> list[bytes]:
    data = value.encode("utf-8")
    return [
        data[start : start + CRED_MAX_BLOB_SIZE]
        for start in range(0, len(data), CRED_MAX_BLOB_SIZE)
    ]


class CredentialManager:
    """Implements password_{lookup,store,clear}_sync like gi.repository.Secret."""

    COLLECTION_DEFAULT = None

    def __init__(self, advapi32=None) -> None:
        self._api = advapi32 or ctypes.WinDLL("advapi32", use_last_error=True)
        self._api.CredReadW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        )
        self._api.CredReadW.restype = wintypes.BOOL
        self._api.CredWriteW.argtypes = (ctypes.POINTER(_Credential), wintypes.DWORD)
        self._api.CredWriteW.restype = wintypes.BOOL
        self._api.CredDeleteW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        self._api.CredDeleteW.restype = wintypes.BOOL
        self._api.CredFree.argtypes = (ctypes.c_void_p,)
        self._api.CredFree.restype = None

    @staticmethod
    def _error(operation: str) -> OSError:
        code = ctypes.get_last_error()
        return OSError(code, f"{operation}: {ctypes.FormatError(code)}")

    def _read(self, target: str) -> bytes | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self._api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise self._error("CredReadW")
        try:
            credential = pointer.contents
            return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        finally:
            self._api.CredFree(pointer)

    def _write(self, target: str, comment: str, blob: bytes) -> None:
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _Credential(
            Type=CRED_TYPE_GENERIC,
            TargetName=target,
            Comment=comment[:255],
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=CRED_PERSIST_LOCAL_MACHINE,
            UserName=USER_NAME,
        )
        if not self._api.CredWriteW(ctypes.byref(credential), 0):
            raise self._error("CredWriteW")

    def _delete(self, target: str) -> bool:
        if self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return True
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return False
        raise self._error("CredDeleteW")

    def _delete_from(self, target: str, index: int) -> None:
        while self._delete(chunk_target(target, index)):
            index += 1

    def password_lookup_sync(self, schema, attributes, _cancellable) -> str | None:
        target = target_name(schema, attributes)
        chunks = []
        while (chunk := self._read(chunk_target(target, len(chunks)))) is not None:
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8") if chunks else None

    def password_store_sync(self, schema, attributes, _collection, label, value, _cancellable):
        target = target_name(schema, attributes)
        chunks = split_blob(value)
        for index, chunk in enumerate(chunks):
            self._write(chunk_target(target, index), label, chunk)
        # A shorter value must not be followed by the tail of an older one.
        self._delete_from(target, len(chunks))
        return True

    def password_clear_sync(self, schema, attributes, _cancellable) -> bool:
        target = target_name(schema, attributes)
        existed = self._delete(target)
        self._delete_from(target, 1)
        return existed
