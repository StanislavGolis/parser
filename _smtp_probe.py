# _smtp_probe.py — проверка входа в SMTP Яндекса (465/SSL и 587/STARTTLS).
import smtplib
import ssl
import sys

HOST = "smtp.yandex.ru"
USER = "stanislav.golis@yandex.ru"


def main() -> None:
    password = sys.argv[1]
    for mode, port in (("ssl", 465), ("starttls", 587)):
        try:
            if mode == "ssl":
                with smtplib.SMTP_SSL(
                    HOST, port, timeout=20, context=ssl.create_default_context()
                ) as smtp:
                    smtp.login(USER, password)
                    print(f"[smtp] {mode}:{port} — вход выполнен, разрешённые команды: {smtp.esmtp_features.get('auth', '')}")
            else:
                with smtplib.SMTP(HOST, port, timeout=20) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    smtp.login(USER, password)
                    print(f"[smtp] {mode}:{port} — вход выполнен")
        except Exception as exc:  # noqa: BLE001
            print(f"[smtp] {mode}:{port} — {exc}")


main()
