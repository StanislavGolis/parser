"""Smoke-проверка источника 4chan (адаптер `chan4`) на живом API.

Запуск из корня проекта (нужен доступ в интернет):

    python -m tests.chan4_smoke [доска]

По умолчанию проверяется доска `/s/` (Sexy Beautiful Women): список разделов,
каталог, и файлы одного непустого треда — имя, тип, размер, md5 (hex), размеры
и ссылка. Как и другие адаптеры, внешних тестов не имеет: проверка идёт по
живому API, потому что источник — это и есть внешний сайт.
"""
import asyncio
import sys

from src.parsers.chan4 import Chan4Adapter


async def check(board: str = "s") -> int:
    async with Chan4Adapter(boards=[board]) as adapter:
        boards = await adapter.fetch_boards() or []
        print(f"разделов в boards.json: {len(boards)}")
        known = {b.slug: b for b in boards}
        target = known.get(board)
        if target is None:
            print(f"  [fail] раздела /{board}/ нет в boards.json")
            return 1
        print(f"  /{board}/: {target.title} [{target.group}] hint={target.hint}")

        catalog = await adapter.fetch_catalog(board)
        if catalog is None:
            print("  [fail] каталог не прочитался")
            return 1
        print(f"  каталог: тредов={len(catalog.threads)}, title={catalog.title!r}")

        with_files = [t for t in catalog.threads if t.files_count > 0]
        if not with_files:
            print("  [fail] в каталоге нет тредов с файлами")
            return 1
        sample = with_files[0]
        print(f"  тред {sample.external_id}: постов={sample.posts_count}, "
              f"файлов={sample.files_count}, fingerprint={sample.fingerprint}")

        files = await adapter.fetch_thread_files(board, sample.external_id)
        if not files:
            print("  [fail] файлы треда не прочитались")
            return 1
        print(f"  файлов: {len(files)}")
        first = files[0]
        meta = first.as_meta()
        print(f"    {first.filename} | {first.media_type} | {first.size_bytes} Б | "
              f"{first.width}x{first.height} | {first.source_url}")
        print(f"    md5={meta['md5']} synthetic={meta['md5_synthetic']} post={first.post_num}")

        problems = []
        if not first.source_url.startswith("https://i.4cdn.org/"):
            problems.append("ссылка не на i.4cdn.org")
        if not first.md5 or len(first.md5) != 32:
            problems.append("md5 не в hex")
        if meta["md5_synthetic"]:
            problems.append("md5 синтетический (ожидался из API)")
        if first.size_bytes <= 0:
            problems.append("не проставлен размер")
        if problems:
            print(f"  [fail] {'; '.join(problems)}")
            return 1
        print("  [ok] адаптер chan4 работает")


def main() -> int:
    board = sys.argv[1] if len(sys.argv) > 1 else "s"
    return asyncio.run(check(board))


if __name__ == "__main__":
    raise SystemExit(main())
