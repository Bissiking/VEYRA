# veyra/storage/biometrics.py
"""Protection au repos des empreintes biométriques.

Principe V0.1 :
- l'empreinte (vecteur) est chiffrée avec AES-GCM via ``cryptography`` ;
- la clé de chiffrement (KEK) est protégée par le coffre-fort de la plateforme :
  * macOS : Keychain (`security` CLI, service ``veyra.biometric``) ;
  * Windows/Linux (V0.1 : non implémenté) -> la KEK est refusée et le profil
    ne peut pas être enregistré (limite documentée, pas de fallback silencieux).
- Aucune image brute n'est stockée.

La suppression du profil efface la ligne SQLite et l'entrée Keychain.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "veyra.biometric"
KEYCHAIN_ACCOUNT = "profile_kek"


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
        return subprocess.run(["security", *args], capture_output=True, text=True, timeout=15)


# --------------------------------------------------------- plateformes non gérées


class UnavailableKeyStorage:
    """Refus explicite sur les plateformes sans coffre intégré (V0.1)."""

    def __init__(self, platform_name: str) -> None:
        self._platform_name = platform_name

    def get_or_create_kek(self) -> bytes:
        raise KeyStorageError(
            f"Protection au repos des empreintes non disponible sur {self._platform_name} "
            "en V0.1. L'enregistrement biométrique est désactivé."
        )

    def delete_kek(self) -> None:
        return None


def create_key_storage() -> KeyStorage:
    """Fabrique le coffre de clés adapté à la plateforme courante."""
    if sys.platform == "darwin":
        return MacKeychainStorage()
    if sys.platform.startswith("win"):
        return UnavailableKeyStorage("Windows (V0.1)")
    return UnavailableKeyStorage("Linux (V0.1)")


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
    def from_json(cls, raw: str | bytes) -> "SealedEmbedding":
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
