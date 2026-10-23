# veyra/storage/biometrics.py
"""Protection au repos des empreintes biométriques.

Principe :
- l'empreinte (vecteur) est chiffrée avec AES-GCM via ``cryptography`` ;
- la clé de chiffrement (KEK) est protégée par le coffre-fort de la plateforme :
  * macOS : Keychain (`security` CLI, service ``veyra.biometric``) ;
  * Windows : DPAPI utilisateur (`CryptProtectData`, blob dans ``%APPDATA%``) ;
  * Linux : Secret Service (`secret-tool`, GNOME Keyring / KWallet) ;
  * sinon -> la KEK est refusée et le profil ne peut pas être enregistré
    (limite documentée, pas de fallback silencieux).
- Aucune image brute n'est stockée.

La suppression du profil efface la ligne SQLite et l'entrée du coffre.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "veyra.biometric"
KEYCHAIN_ACCOUNT = "profile_kek"

SECRET_TOOL_LABEL = "VEYRA — empreinte biométrique"


class _DATA_BLOB(ctypes.Structure):
    """Structure ``DATA_BLOB`` du DPAPI (opaque pour les non-Windows)."""

    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


class KeyStorageError(RuntimeError):
    """Le coffre clés de la plateforme n'est pas disponible."""


class KeyStorage(Protocol):
    """Interface du coffre de clés de la plateforme."""

    def get_or_create_kek(self) -> bytes:
        """Retourne la KEK (32 octets), la créant au premier appel."""
        ...

    def delete_kek(self) -> None:
        """Supprime la KEK du coffre (si présente)."""
        ...


# ------------------------------------------------------------- macOS (Keychain)


class MacKeychainStorage:
    """KEK stockée dans le Keychain macOS via la CLI `security` (pas de sudo)."""

    def get_or_create_kek(self) -> bytes:
        existing = self._security(["find-generic-password", "-w",
                                   "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT])
        if existing is not None and existing.returncode == 0:
            try:
                return base64.b64decode(existing.stdout.strip())
            except ValueError:
                logger.warning("Entrée Keychain corrompue, régénération de la clé.")
        kek = AESGCM.generate_key(bit_length=256)
        b64 = base64.b64encode(kek).decode("ascii")
        add = self._security(["add-generic-password", "-U",
                              "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
                              "-w", b64])
        if add.returncode != 0:
            raise KeyStorageError(
                "Impossible d'écrire dans le Keychain macOS (autorisations refusées). "
                "VEYRA ne protégera aucune empreinte sans coffre de clés."
            )
        return kek

    def delete_kek(self) -> None:
        self._security(["delete-generic-password",
                        "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT])

    @staticmethod
    def _security(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["security", *args], check=False,
                              capture_output=True, text=True, timeout=15)


# ----------------------------------------------------------- Windows (DPAPI)


def _dpapi_available() -> bool:
    return sys.platform.startswith("win") and hasattr(ctypes, "windll")


class WindowsDpapiStorage:
    """KEK protégée par le DPAPI utilisateur, blob stocké dans ``%APPDATA%``.

    ``CryptProtectData`` lie le blob à l'utilisateur Windows courant : copier
    le fichier sur un autre compte ou une autre machine le rend inexploitable.
    """

    _BLOB_NAME = "profile_kek.dpapi"

    def __init__(self, appdata: Path | None = None) -> None:
        self._dir = Path(appdata) if appdata else (
            Path(os.environ.get("APPDATA", "")) / "VEYRA"
        )

    def get_or_create_kek(self) -> bytes:
        if not _dpapi_available():
            raise KeyStorageError(
                "DPAPI indisponible : l'appareil n'est pas une session Windows. "
                "L'enregistrement biométrique est désactivé."
            )
        blob_path = self._dir / self._BLOB_NAME
        if blob_path.is_file():
            try:
                protected = blob_path.read_bytes()
                return self._unprotect(protected)
            except (OSError, KeyStorageError):
                logger.warning(
                    "Blob DPAPI illisible ou corrompu, régénération de la clé.")
        kek = AESGCM.generate_key(bit_length=256)
        protected = self._protect(kek)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            # 0o600 : lecture seule pour l'utilisateur courant (best-effort).
            blob_path.write_bytes(protected)
            try:
                os.chmod(blob_path, 0o600)
            except OSError:
                pass
        except OSError as exc:
            raise KeyStorageError(
                "Impossible d'écrire le coffre DPAPI (%APPDATA%). "
                "VEYRA ne protégera aucune empreinte sans coffre de clés."
            ) from exc
        return kek

    def delete_kek(self) -> None:
        blob_path = self._dir / self._BLOB_NAME
        try:
            blob_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Effacement du blob DPAPI partiellement échoué.")

    @staticmethod
    def _protect(data: bytes) -> bytes:
        # CryptProtectData lie le blob à l'utilisateur + la machine.
        buf = ctypes.create_string_buffer(data)
        in_blob = _DATA_BLOB(len(data), ctypes.cast(
            buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        try:
            ok = ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(in_blob), None, None, None, None, 0,
                ctypes.byref(out_blob))
            if not ok:
                raise KeyStorageError(
                    "CryptProtectData a échoué : coffre DPAPI indisponible.")
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if out_blob.pbData:
                ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    @staticmethod
    def _unprotect(protected: bytes) -> bytes:
        buf = ctypes.create_string_buffer(protected)
        in_blob = _DATA_BLOB(len(protected), ctypes.cast(
            buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = _DATA_BLOB()
        try:
            ok = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None, 0,
                ctypes.byref(out_blob))
            if not ok:
                raise KeyStorageError(
                    "CryptUnprotectData a échoué : le blob DPAPI n'appartient "
                    "pas à cet utilisateur ou cette machine.")
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            if out_blob.pbData:
                ctypes.windll.kernel32.LocalFree(out_blob.pbData)


# ----------------------------------------------------- Linux (Secret Service)


class LinuxSecretServiceStorage:
    """KEK dans le Secret Service via ``secret-tool`` (GNOME Keyring / KWallet).

    Aucune dépendance Python : la CLI ``libsecret-tools`` suffit. Si elle est
    absente, la KEK est refusée explicitement (pas de stockage en clair).
    """

    @staticmethod
    def _run(args: list[str], stdin: bytes | None = None
             ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["secret-tool", *args], check=False, input=stdin,
            capture_output=True, timeout=15,
        )

    def get_or_create_kek(self) -> bytes:
        if not sys.platform.startswith("linux"):
            raise KeyStorageError(
                "Secret Service indisponible : l'appareil n'est pas une "
                "session Linux. L'enregistrement biométrique est désactivé.")
        lookup = self._run(["lookup", "service", KEYCHAIN_SERVICE,
                            "account", KEYCHAIN_ACCOUNT])
        if lookup.returncode == 0 and lookup.stdout:
            # secret-tool ajoute un "\n" final ; on ne strippe PAS les octets
            # binaires (une KEK peut se terminer par un octet "blanc").
            raw = lookup.stdout
            if raw.endswith(b"\n"):
                raw = raw[:-1]
            return bytes(raw)
        kek = AESGCM.generate_key(bit_length=256)
        store = self._run(
            ["store", "--label", SECRET_TOOL_LABEL,
             "service", KEYCHAIN_SERVICE, "account", KEYCHAIN_ACCOUNT],
            stdin=kek,
        )
        if store.returncode != 0:
            raise KeyStorageError(
                "Impossible d'écrire dans le Secret Service Linux "
                "(cléring/agent absent ou refus). "
                "VEYRA ne protégera aucune empreinte sans coffre de clés.")
        return kek

    def delete_kek(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        self._run(["clear", "service", KEYCHAIN_SERVICE,
                   "account", KEYCHAIN_ACCOUNT])


# --------------------------------------------------------- plateformes non gérées


class UnavailableKeyStorage:
    """Refus explicite sur les plateformes sans coffre intégré."""

    def __init__(self, platform_name: str) -> None:
        self._platform_name = platform_name

    def get_or_create_kek(self) -> bytes:
        raise KeyStorageError(
            f"Protection au repos des empreintes non disponible sur {self._platform_name}. "
            "L'enregistrement biométrique est désactivé."
        )

    def delete_kek(self) -> None:
        return None


def create_key_storage() -> KeyStorage:
    """Fabrique le coffre de clés adapté à la plateforme courante."""
    if sys.platform == "darwin":
        return MacKeychainStorage()
    if sys.platform.startswith("win"):
        return WindowsDpapiStorage()
    if sys.platform.startswith("linux"):
        return LinuxSecretServiceStorage()
    return UnavailableKeyStorage(sys.platform)


# ------------------------------------------------------------- coffre biométrique


@dataclass(frozen=True)
class SealedEmbedding:
    """Empreinte chiffrée, sérialisable pour SQLite."""

    nonce_b64: str
    ciphertext_b64: str
    key_id: str
    algo: str = "AESGCM-256"

    def to_json(self) -> str:
        return json.dumps({"n": self.nonce_b64, "c": self.ciphertext_b64,
                           "k": self.key_id, "a": self.algo})

    @classmethod
    def from_json(cls, raw: str | bytes) -> SealedEmbedding:
        data = json.loads(raw)
        return cls(nonce_b64=data["n"], ciphertext_b64=data["c"],
                   key_id=data["k"], algo=data.get("a", "AESGCM-256"))


class BiometricVault:
    """Chiffre/déchiffre les empreintes et gère la clé via le coffre plateforme."""

    def __init__(self, key_storage: KeyStorage) -> None:
        self._key_storage = key_storage
        self._kek: bytes | None = None

    @property
    def available(self) -> bool:
        try:
            self._load_kek()
            return True
        except KeyStorageError:
            return False

    def seal(self, plaintext: bytes) -> SealedEmbedding:
        kek = self._load_kek()
        nonce = os.urandom(12)
        ct = AESGCM(kek).encrypt(nonce, plaintext, associated_data=b"veyra.embedding.v1")
        return SealedEmbedding(
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(ct).decode("ascii"),
            key_id="primary",
        )

    def open(self, sealed: SealedEmbedding) -> bytes:
        kek = self._load_kek()
        try:
            return AESGCM(kek).decrypt(
                base64.b64decode(sealed.nonce_b64),
                base64.b64decode(sealed.ciphertext_b64),
                associated_data=b"veyra.embedding.v1",
            )
        except InvalidTag as exc:
            raise KeyStorageError(
                "Déchiffrement impossible : clé Keychain absente ou modifiée."
            ) from exc

    def destroy(self) -> None:
        """Suppression complète : efface la clé du coffre plateforme."""
        self._key_storage.delete_kek()
        self._kek = None

    def _load_kek(self) -> bytes:
        if self._kek is None:
            self._kek = self._key_storage.get_or_create_kek()
        return self._kek
