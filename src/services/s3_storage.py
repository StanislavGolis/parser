# src/services/s3_storage.py
"""Загрузчик в S3-совместимое хранилище (Timeweb Cloud) через boto3.

- Не блокирует event loop: синхронные вызовы boto3 уходят в asyncio.to_thread.
- Если S3 не настроен в .env — безопасно деградирует:
  файлы остаются в локальном хранилище (status='downloaded').
"""
import asyncio
import mimetypes
from pathlib import Path
from typing import List, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from src.core.config import settings


class S3Storage:
    def __init__(self):
        self.key_id = settings.storage_access_key
        self.application_key = settings.storage_secret_key
        self.bucket_name = settings.storage_bucket
        self.endpoint_url = settings.storage_endpoint
        self.region = settings.storage_region
        self.addressing_style = settings.S3_ADDRESSING_STYLE
        self.signed_url_ttl = settings.S3_SIGNED_URL_TTL

        self.is_configured = bool(
            self.key_id
            and self.application_key
            and self.bucket_name
        )

        self.client = None
        if self.is_configured:
            self._init_client()
        else:
            print("   [warn] S3 не настроен — файлы будут сохранены локально")

    # ───────────────────── Инициализация ─────────────────────

    def _init_client(self) -> None:
        """Создаёт S3-клиент boto3 и проверяет доступ к бакету."""
        try:
            self.client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.key_id,
                aws_secret_access_key=self.application_key,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={"addressing_style": self.addressing_style},
                    connect_timeout=30,
                    read_timeout=600,
                    retries={"max_attempts": 3},
                ),
            )
            # Проверка прав доступа к бакету
            self.client.head_bucket(Bucket=self.bucket_name)
            print(f"   [ok] Подключение к S3 установлено (boto3), бакет: {self.bucket_name}")
        except Exception as e:
            self.is_configured = False
            self.client = None
            print(f"   [warn] Ошибка подключения к S3: {e} — файлы будут сохранены локально")

    # ───────────────────── Операции с файлами ─────────────────────

    async def upload_file(
        self,
        local_path: Path,
        remote_key: str,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Загружает файл в S3. Возвращает remote_key или None при ошибке.

        Content-Type задаётся явно (content_type или по расширению имени),
        иначе S3 хранит application/octet-stream и видео не воспроизводится
        браузером по presigned URL.
        """
        if not self.is_configured or self.client is None:
            return None

        extra_args = {}
        ct = content_type or mimetypes.guess_type(remote_key)[0]
        if ct:
            extra_args["ContentType"] = ct

        try:
            await asyncio.to_thread(
                self.client.upload_file,
                str(local_path),
                self.bucket_name,
                remote_key,
                ExtraArgs=extra_args,
            )
            print(f"   [ok] Загружен в S3: {remote_key} ({ct or 'без Content-Type'})")
            return remote_key
        except Exception as e:
            print(f"   [err] Ошибка загрузки в S3: {e}")
            return None

    async def list_keys(self, prefix: str = "") -> Optional[List[str]]:
        """Возвращает список ключей (Objects) в бакете, постранично."""
        if not self.is_configured or self.client is None:
            return None

        try:
            keys: List[str] = []

            def _list_all() -> List[str]:
                result: List[str] = []
                paginator = self.client.get_paginator("list_objects_v2")
                for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                    for obj in page.get("Contents") or []:
                        result.append(obj["Key"])
                return result

            keys = await asyncio.to_thread(_list_all)
            return keys
        except Exception as e:
            print(f"   [err] Ошибка листинга S3: {e}")
            return None

    async def upload_bytes(
        self,
        data: bytes,
        remote_key: str,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Загружает объект из памяти (деривативы: превью / 720p)."""
        if not self.is_configured or self.client is None:
            return None
        try:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=self.bucket_name,
                Key=remote_key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
            )
            return remote_key
        except Exception as e:
            print(f"   [err] Ошибка загрузки объекта в S3: {e}")
            return None

    async def download_to_file(self, remote_key: str, dest: Path) -> bool:
        """Скачивает объект из S3 в локальный файл (бэкфилл деривативов, прогрев кэша)."""
        if not self.is_configured or self.client is None:
            return False
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                self.client.download_file, self.bucket_name, remote_key, str(dest)
            )
            return dest.exists() and dest.stat().st_size > 0
        except Exception as e:
            print(f"   [err] Ошибка скачивания из S3: {e}")
            # Недокачанный файл не оставляем (иначе мусор в кэше/бэкфилле)
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    async def delete_object(self, remote_key: str) -> bool:
        """Удаляет объект из бакета."""
        if not self.is_configured or self.client is None:
            return False

        try:
            await asyncio.to_thread(
                self.client.delete_object,
                Bucket=self.bucket_name,
                Key=remote_key,
            )
            print(f"   [del]  Удалён объект из S3: {remote_key}")
            return True
        except Exception as e:
            print(f"   [err] Ошибка удаления из S3: {e}")
            return False

    async def delete_keys(self, keys: List[str]) -> bool:
        """Пакетно удаляет объекты из бакета (батчами до 1000)."""
        if not self.is_configured or self.client is None or not keys:
            return False

        def _delete_batch(batch: List[str]) -> None:
            self.client.delete_objects(
                Bucket=self.bucket_name,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )

        try:
            for i in range(0, len(keys), 1000):
                await asyncio.to_thread(_delete_batch, keys[i:i + 1000])
            print(f"   [del]  Удалено объектов из S3: {len(keys)}")
            return True
        except Exception as e:
            print(f"   [err] Ошибка пакетного удаления из S3: {e}")
            return False

    def generate_presigned_url(self, remote_key: str, expires_in: Optional[int] = None) -> Optional[str]:
        """Генерирует временную подписанную ссылку на файл (по умолчанию 1 час).

        Нужно для бэкенда сайта (отдача приватного контента).
        """
        if not self.is_configured or self.client is None:
            return None

        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": remote_key},
                ExpiresIn=expires_in or self.signed_url_ttl,
            )
        except Exception as e:
            print(f"   [err] Ошибка генерации подписанного URL: {e}")
            return None

    # ─────────────── Потоковая отдача (прокси через API) ───────────────

    async def open_object_stream(self, remote_key: str, range_header: Optional[str] = None):
        """Открывает объект для потоковой отдачи через наш API.

        Возвращает словарь с телом (botocore StreamingBody) и метаданными либо
        None, если объекта нет. Синхронные вызовы boto3 выполняются в отдельном
        потоке, чтобы не блокировать event loop.
        """
        if not self.is_configured or self.client is None:
            return None

        params = {"Bucket": self.bucket_name, "Key": remote_key}
        if range_header:
            params["Range"] = range_header

        try:
            resp = await asyncio.to_thread(self.client.get_object, **params)
        except ClientError as e:
            code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "NoSuchBucket", "404"):
                return None
            print(f"   [err] Ошибка чтения из S3: {e}")
            return None
        except Exception as e:
            print(f"   [err] Ошибка чтения из S3: {e}")
            return None

        return {
            "body": resp.get("Body"),
            "content_type": resp.get("ContentType"),
            "content_length": resp.get("ContentLength"),
            "content_range": resp.get("ContentRange"),
            "accept_ranges": resp.get("AcceptRanges"),
            "etag": resp.get("ETag"),
        }
