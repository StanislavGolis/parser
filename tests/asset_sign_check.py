# tests/asset_sign_check.py — быстрая проверка подписи ссылок (запуск вручную).
#
# Запуск: python tests/asset_sign_check.py  (секрет подставляется в окружение)
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ASSET_LINK_SECRET"] = "unit-test-secret"
os.environ["ASSET_LINK_TTL_MINUTES"] = "60"

from src.services import asset_sign  # noqa: E402


def main() -> int:
    assert asset_sign.enabled(), "подписи должны включаться при заданном секрете"
    version = "abc123-2"

    first = asset_sign.sign(101, "thumb", version)
    second = asset_sign.sign(101, "thumb", version)
    assert first and second, "sign вернул None"
    assert first == second, f"окно «дрожит»: {first} != {second}"

    expires, signature = first
    assert expires > time.time() + 3000, "ссылка должна жить минимум окно"
    assert asset_sign.verify(101, "thumb", version, str(expires), signature), "валидная не прошла"
    assert not asset_sign.verify(102, "thumb", version, str(expires), signature), "чужой media_id"
    assert not asset_sign.verify(101, "web", version, str(expires), signature), "чужой kind"
    assert not asset_sign.verify(101, "thumb", "other", str(expires), signature), "чужая версия"
    assert not asset_sign.verify(101, "thumb", version, str(expires + 60), signature), "изменённый срок"
    assert not asset_sign.verify(101, "thumb", version, "0", signature), "просроченная подпись"
    assert not asset_sign.verify(101, "thumb", version, str(expires), signature[:-1] + "x"), "битая подпись"
    assert not asset_sign.verify(101, "thumb", version, None, None), "без подписи"

    past_sig = asset_sign._digest(asset_sign._payload(101, "thumb", version, 1))
    assert not asset_sign.verify(101, "thumb", version, "1", past_sig), "истёкший exp приняли"

    print(f"подписи ок: exp={expires} (живёт {(expires - time.time()) / 60:.0f} мин), s={signature[:12]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
