# src/services/b2_uploader.py
"""Загрузчик в Backblaze B2 (временная реализация на прямом REST API).

Полный переезд на boto3 / S3-API — Этап 4 роадмапа ТЗ v3.
Если B2 не настроен в .env — загрузчик безопасно деградирует:
файлы остаются в локальном хранилище (status='downloaded').
"""
import asyncio
import hashlib
from pathlib import Path
from typing import Optional

import requests

from src.core.config import settings


class B2Uploader:
    PLACEHOLDER_BUCKET = "your-media-bucket"

    def __init__(self):
        self.key_id = settings.B2_KEY_ID
        self.application_key = settings.B2_APPLICATION_KEY
        self.bucket_name = settings.B2_BUCKET_NAME

        self.auth_token: Optional[str] = None
        self.api_url: Optional[str] = None
        self.account_id: Optional[str] = None
        self.bucket_id: Optional[str] = None

        self.is_configured = bool(
            self.key_id
            and self.application_key
            and self.bucket_name
            and self.bucket_name != self.PLACEHOLDER_BUCKET
        )

        if self.is_configured:
            self._authorize_sync()
        else:
            print("   ⚠️ Backblaze B2 не настроен — файлы будут сохранены локально")

    # ---------- Авторизация ----------

    def _authorize_sync(self):
        try:
            response = requests.get(
                "https://api.backblazeb2.com/b2api/v1/b2_authorize_account",
                auth=(self.key_id, self.application_key),
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            self.auth_token = data["authorizationToken"]
            self.api_url = data["apiUrl"]
            self.account_id = data["accountId"]

            bucket_response = requests.post(
                f"{self.api_url}/b2api/v1/b2_list_buckets",
                headers={"Authorization": self.auth_token},
                json={"accountId": self.account_id},
                timeout=30,
            )
            bucket_response.raise_for_status()
            buckets = bucket_response.json().get("buckets", [])

            for bucket in buckets:
                if bucket["bucketName"] == self.bucket_name:
                    self.bucket_id = bucket["bucketId"]
                    break

            if not self.bucket_id:
                self.is_configured = False
                print(f"   ❌ Bucket '{self.bucket_name}' не найден в B2")
                return

            print("   ✅ Авторизован в Backblaze B2")

        except Exception as e:
            self.is_configured = False
            print(f"   ⚠️ Ошибка авторизации в B2: {e}")

    # ---------- Загрузка ----------

    async def upload_file(self, local_path: Path, remote_key: str) -> Optional[str]:
        """Загружает файл в B2. Возвращает fileId или None (если B2 недоступен)."""
        if not self.is_configured or not self.auth_token or not self.bucket_id:
            return None

        try:
            loop = asyncio.get_event_loop()

            def _get_upload_url():
                response = requests.post(
                    f"{self.api_url}/b2api/v1/b2_get_upload_url",
                    headers={"Authorization": self.auth_token},
                    json={"bucketId": self.bucket_id},
                    timeout=30,
                )
                response.raise_for_status()
                return response.json()

            upload_data = await loop.run_in_executor(None, _get_upload_url)
            upload_url = upload_data["uploadUrl"]
            upload_auth = upload_data["authorizationToken"]

            with open(local_path, "rb") as f:
                file_data = f.read()

            sha1 = hashlib.sha1(file_data).hexdigest()

            def _upload():
                response = requests.post(
                    upload_url,
                    headers={
                        "Authorization": upload_auth,
                        "X-Bz-File-Name": remote_key,
                        "Content-Type": "b2/x-auto",
                        "X-Bz-Content-Sha1": sha1,
                    },
                    data=file_data,
                    timeout=600,
                )
                response.raise_for_status()
                return response.json()

            result = await loop.run_in_executor(None, _upload)

            print(f"   ✅ Загружен в B2: {remote_key}")
            return result.get("fileId")

        except Exception as e:
            print(f"   ❌ Ошибка загрузки в B2: {e}")
            return None