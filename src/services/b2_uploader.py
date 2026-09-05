import requests
import asyncio
from pathlib import Path
from typing import Optional
import hashlib
import base64
import hmac
import time
from urllib.parse import quote

from src.core.config import settings


class B2Uploader:
    """Загрузчик файлов в Backblaze B2 через прямые API запросы"""
    
    def __init__(self):
        self.key_id = settings.B2_KEY_ID
        self.application_key = settings.B2_APPLICATION_KEY
        self.bucket_name = settings.B2_BUCKET_NAME
        
        self.auth_token = None
        self.api_url = None
        self.account_id = None
        self.bucket_id = None
        
        # Аутентификация
        self._authorize_sync()
    
    def _authorize_sync(self):
        """Синхронная авторизация (вызывается при инициализации)"""
        try:
            response = requests.get(
                "https://api.backblazeb2.com/b2api/v1/b2_authorize_account",
                auth=(self.key_id, self.application_key)
            )
            response.raise_for_status()
            data = response.json()
            
            self.auth_token = data['authorizationToken']
            self.api_url = data['apiUrl']
            self.account_id = data['accountId']
            
            # Получаем bucketId
            bucket_response = requests.post(
                f"{self.api_url}/b2api/v1/b2_list_buckets",
                headers={'Authorization': self.auth_token},
                json={'accountId': self.account_id}
            )
            bucket_response.raise_for_status()
            buckets = bucket_response.json()['buckets']
            
            for bucket in buckets:
                if bucket['bucketName'] == self.bucket_name:
                    self.bucket_id = bucket['bucketId']
                    break
            
            if not self.bucket_id:
                raise Exception(f"Bucket '{self.bucket_name}' not found")
                
            print("   ✅ Авторизован в Backblaze B2")
            
        except Exception as e:
            print(f"   ❌ Ошибка авторизации в B2: {e}")
            raise
    
    async def upload_file(self, local_path: Path, remote_key: str) -> Optional[str]:
        """Загружает файл в B2 через прямой API"""
        if not self.auth_token:
            print("   ❌ Нет авторизации")
            return None
        
        try:
            loop = asyncio.get_event_loop()
            
            # Получаем URL для загрузки
            def _get_upload_url():
                response = requests.post(
                    f"{self.api_url}/b2api/v1/b2_get_upload_url",
                    headers={'Authorization': self.auth_token},
                    json={'bucketId': self.bucket_id}
                )
                response.raise_for_status()
                return response.json()
            
            upload_data = await loop.run_in_executor(None, _get_upload_url)
            upload_url = upload_data['uploadUrl']
            upload_auth = upload_data['authorizationToken']
            
            # Читаем файл
            with open(local_path, 'rb') as f:
                file_data = f.read()
            
            # SHA-1 файла
            sha1 = hashlib.sha1(file_data).hexdigest()
            
            # Загружаем
            def _upload():
                response = requests.post(
                    upload_url,
                    headers={
                        'Authorization': upload_auth,
                        'X-Bz-File-Name': remote_key,
                        'Content-Type': 'b2/x-auto',
                        'X-Bz-Content-Sha1': sha1
                    },
                    data=file_data
                )
                response.raise_for_status()
                return response.json()
            
            result = await loop.run_in_executor(None, _upload)
            
            print(f"   ✅ Загружен в B2: {remote_key}")
            return result['fileId']
            
        except Exception as e:
            print(f"   ❌ Ошибка загрузки в B2: {e}")
            return None