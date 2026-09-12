# _probe_previews.py — проверка превью раздела так, как их видит браузер.
import json
import urllib.error
import urllib.request

BASE = "http://37.221.66.168"
SLUG = "gg"
PAGES = (1, 2, 3)
PER_PAGE = 30


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def magic(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:2] == b"\xff\xd8":
        return "JPEG"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "MKV/WebM"
    if data[4:8] == b"ftyp":
        return "MP4"
    return f"?{data[:8]!r}"


def main() -> None:
    total = 0
    broken = []
    for page in PAGES:
        status, headers, body = get(f"{BASE}/api/v1/boards/{SLUG}/media?page={page}&per_page={PER_PAGE}")
        if status != 200:
            print(f"[preview] страница {page}: HTTP {status} — {body[:200]!r}")
            continue
        items = json.loads(body).get("items") or []
        for item in items:
            total += 1
            thumb = item.get("thumb_url")
            if not thumb:
                broken.append((item["id"], "нет thumb_url", item.get("locked"), item.get("is_premium")))
                continue
            url = BASE + thumb if thumb.startswith("/") else thumb
            st, hdrs, data = get(url)
            kind = magic(data) if data else "пусто"
            ok = st == 200 and kind in ("WEBP", "PNG", "JPEG")
            if not ok:
                broken.append((item["id"], f"HTTP {st}, {len(data)} Б, {kind}", item.get("locked"), item.get("is_premium")))

    print(f"[preview] проверено превью: {total}, битых: {len(broken)}")
    for media_id, why, locked, premium in broken[:15]:
        print(f"[preview]   media {media_id}: {why} (premium={premium}, locked={locked})")


main()
