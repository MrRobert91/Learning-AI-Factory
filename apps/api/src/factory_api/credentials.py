"""Encrypted storage for provider credentials and short-lived OAuth secrets."""

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from factory_api.config import Settings, get_settings
from factory_api.db import engine
from factory_api.models import OAuthToken

logger = logging.getLogger(__name__)


class CredentialConfigurationError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CredentialKey:
    key_id: str
    key: bytes


class CredentialCipher:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.keys = self._parse_keys(self.settings.credential_encryption_keys)
        self.by_id = {item.key_id: item for item in self.keys}

    @staticmethod
    def _parse_keys(raw: str) -> tuple[CredentialKey, ...]:
        parsed: list[CredentialKey] = []
        for entry in raw.split(","):
            if not entry.strip():
                continue
            try:
                key_id, encoded = entry.strip().split(":", 1)
                key = base64.urlsafe_b64decode(encoded.encode())
            except (ValueError, TypeError) as exc:
                raise CredentialConfigurationError(
                    "CREDENTIAL_ENCRYPTION_KEYS must use kid:urlsafe-base64 format"
                ) from exc
            if not key_id or len(key) != 32:
                raise CredentialConfigurationError(
                    "Each credential encryption key must have an id and decode to 32 bytes"
                )
            if any(existing.key_id == key_id for existing in parsed):
                raise CredentialConfigurationError("Credential encryption key ids must be unique")
            parsed.append(CredentialKey(key_id, key))
        if not parsed:
            raise CredentialConfigurationError("At least one credential encryption key is required")
        return tuple(parsed)

    @property
    def active_key_id(self) -> str:
        return self.keys[0].key_id

    def encrypt_json(self, value: dict[str, Any], *, associated_data: str) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        encrypted = AESGCM(self.keys[0].key).encrypt(nonce, plaintext, associated_data.encode())
        return json.dumps(
            {
                "v": 1,
                "kid": self.keys[0].key_id,
                "nonce": base64.urlsafe_b64encode(nonce).decode(),
                "ciphertext": base64.urlsafe_b64encode(encrypted).decode(),
            },
            separators=(",", ":"),
        )

    def decrypt_json(self, envelope: str, *, associated_data: str) -> tuple[dict[str, Any], str]:
        try:
            payload = json.loads(envelope)
            key_id = payload["kid"]
            key = self.by_id[key_id].key
            nonce = base64.urlsafe_b64decode(payload["nonce"])
            ciphertext = base64.urlsafe_b64decode(payload["ciphertext"])
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, associated_data.encode())
            value = json.loads(plaintext)
        except (
            KeyError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
            InvalidTag,
        ) as exc:
            raise CredentialDecryptionError(
                "Stored credential cannot be decrypted with the configured key ring"
            ) from exc
        if not isinstance(value, dict):
            raise CredentialDecryptionError("Stored credential payload is invalid")
        return value, key_id

    @staticmethod
    def is_encrypted(value: str) -> bool:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict) and payload.get("v") == 1 and bool(payload.get("kid"))


class CredentialStore:
    def __init__(self, settings: Settings | None = None):
        self.cipher = CredentialCipher(settings)

    @staticmethod
    def _aad(provider: str, user_id: str) -> str:
        return f"oauth-token\0{provider}\0{user_id}"

    def get(
        self, db: Session, *, provider: str, user_id: str | None = None
    ) -> dict[str, Any] | None:
        stmt = select(OAuthToken).where(OAuthToken.provider == provider)
        if user_id is not None:
            stmt = stmt.where(OAuthToken.user_id == user_id)
        token = db.scalars(stmt.limit(1)).first()
        if token is None:
            return None
        aad = self._aad(provider, token.user_id)
        if self.cipher.is_encrypted(token.token_json):
            value, key_id = self.cipher.decrypt_json(token.token_json, associated_data=aad)
        else:
            try:
                value = json.loads(token.token_json)
            except json.JSONDecodeError as exc:
                raise CredentialDecryptionError("Stored legacy credential is invalid") from exc
            if not isinstance(value, dict):
                raise CredentialDecryptionError("Stored legacy credential is invalid")
            key_id = "legacy"
        if key_id != self.cipher.active_key_id:
            replacement = self.cipher.encrypt_json(value, associated_data=aad)
            verified, _ = self.cipher.decrypt_json(replacement, associated_data=aad)
            if verified != value:
                raise CredentialDecryptionError("Credential rotation verification failed")
            token.token_json = replacement
            db.commit()
        return value

    def put(
        self,
        db: Session,
        *,
        provider: str,
        user_id: str,
        value: dict[str, Any],
    ) -> OAuthToken:
        token = db.scalars(
            select(OAuthToken)
            .where(OAuthToken.provider == provider, OAuthToken.user_id == user_id)
            .limit(1)
        ).first()
        encrypted = self.cipher.encrypt_json(value, associated_data=self._aad(provider, user_id))
        verified, _ = self.cipher.decrypt_json(
            encrypted, associated_data=self._aad(provider, user_id)
        )
        if verified != value:
            raise CredentialDecryptionError("Credential write verification failed")
        if token is None:
            token = OAuthToken(user_id=user_id, provider=provider, token_json=encrypted)
            db.add(token)
        else:
            token.token_json = encrypted
        db.commit()
        db.refresh(token)
        return token

    def delete(self, db: Session, *, provider: str, user_id: str) -> None:
        token = db.scalars(
            select(OAuthToken)
            .where(OAuthToken.provider == provider, OAuthToken.user_id == user_id)
            .limit(1)
        ).first()
        if token is not None:
            db.delete(token)
            db.commit()


def migrate_legacy_credentials(db: Session) -> int:
    """Encrypt plaintext OAuth rows atomically and verify before replacing them."""
    cipher = CredentialCipher()
    rows = db.scalars(select(OAuthToken)).all()
    replacements: list[tuple[OAuthToken, str]] = []
    for token in rows:
        if cipher.is_encrypted(token.token_json):
            cipher.decrypt_json(
                token.token_json,
                associated_data=CredentialStore._aad(token.provider, token.user_id),
            )
            continue
        try:
            legacy = json.loads(token.token_json)
        except json.JSONDecodeError as exc:
            raise CredentialDecryptionError(
                f"Legacy {token.provider} credential is invalid; restore the database backup"
            ) from exc
        if not isinstance(legacy, dict):
            raise CredentialDecryptionError("Legacy credential payload is invalid")
        aad = CredentialStore._aad(token.provider, token.user_id)
        encrypted = cipher.encrypt_json(legacy, associated_data=aad)
        verified, _ = cipher.decrypt_json(encrypted, associated_data=aad)
        if verified != legacy:
            raise CredentialDecryptionError("Legacy credential migration verification failed")
        replacements.append((token, encrypted))
    if not replacements:
        return 0

    db.execute(text("PRAGMA secure_delete = ON"))
    for token, encrypted in replacements:
        token.token_json = encrypted
    db.commit()

    if engine.dialect.name == "sqlite":
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.exec_driver_sql("VACUUM")
    logger.info("Encrypted legacy OAuth credentials", extra={"credential_count": len(replacements)})
    return len(replacements)
