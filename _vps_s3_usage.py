# _vps_s3_usage.py — оценка объёма медиа в S3 (сколько займёт на диске VPS).
import sys
from collections import defaultdict

sys.path.insert(0, "/app")

from src.services.s3_storage import S3Storage


def main() -> None:
    s3 = S3Storage()
    if not s3.is_configured:
        print("[usage] S3 не настроен")
        return

    paginator = s3.client.get_paginator("list_objects_v2")
    total = 0
    count = 0
    by_suffix = defaultdict(lambda: [0, 0])
    biggest = []
    for page in paginator.paginate(Bucket=s3.bucket_name):
        for obj in page.get("Contents", []):
            size = int(obj["Size"])
            key = obj["Key"]
            total += size
            count += 1
            suffix = key.rsplit(".", 1)[-1].lower() if "." in key else "no-ext"
            by_suffix[suffix][0] += 1
            by_suffix[suffix][1] += size
            biggest.append((size, key))

    biggest.sort(reverse=True)
    print(f"[usage] объектов: {count}, всего: {total / 1024 ** 3:.2f} ГБ ({total / 1024 ** 2:.0f} МБ)")
    for suffix, (cnt, size) in sorted(by_suffix.items(), key=lambda kv: -kv[1][1]):
        print(f"[usage]   .{suffix}: {cnt} шт, {size / 1024 ** 2:.0f} МБ")
    print("[usage] крупнейшие объекты:")
    for size, key in biggest[:5]:
        print(f"[usage]   {size / 1024 ** 2:.1f} МБ — {key}")
    if count:
        print(f"[usage] средний размер: {total / count / 1024 ** 2:.2f} МБ")


main()
