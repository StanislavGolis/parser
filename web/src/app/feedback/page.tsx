"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import type { FeedbackItem, UserOut } from "@/lib/types";

/** Темы обращения: `?topic=premium` приходит с кнопки «Запросить премиум». */
const TOPICS: Array<{ value: string; label: string; hint: string }> = [
  { value: "premium", label: "Премиум-доступ", hint: "Запросить или продлить доступ" },
  { value: "bug", label: "Баг", hint: "Что-то не работает или выглядит сломанным" },
  { value: "idea", label: "Идея", hint: "Чего не хватает и что улучшить" },
  { value: "content", label: "Контент", hint: "Файл, раздел или запись" },
  { value: "other", label: "Другое", hint: "Всё остальное" },
];

const MIN_MESSAGE = 10;

/**
 * Обратная связь: заявка сохраняется в БД и письмом уходит админам.
 * Вход не обязателен — тогда контактом служит указанный email.
 */
export default function FeedbackPage() {
  const params = useSearchParams();
  const topicFromUrl = params.get("topic");
  const [topic, setTopic] = useState(
    TOPICS.some((t) => t.value === topicFromUrl) ? String(topicFromUrl) : "idea",
  );
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [user, setUser] = useState<UserOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<FeedbackItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Ловушка для ботов: поле скрыто, люди его не заполняют
  const [website, setWebsite] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        setUser(await apiSend<UserOut>("/api/v1/auth/me"));
      } catch {
        setUser(null);
      }
    })();
  }, []);

  const active = useMemo(
    () => TOPICS.find((t) => t.value === topic) ?? TOPICS[TOPICS.length - 1],
    [topic],
  );

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        const item = await apiSend<FeedbackItem>("/api/v1/feedback", {
          method: "POST",
          body: {
            topic,
            message,
            email: email.trim() || undefined,
            page_url: typeof window !== "undefined" ? window.location.href : undefined,
            website,
          },
        });
        setSent(item);
        setMessage("");
        setWebsite("");
      } catch (err) {
        setError(
          err instanceof ApiError ? (err.detail ?? err.message) : "Не удалось отправить обращение",
        );
      } finally {
        setBusy(false);
      }
    },
    [topic, message, email, website],
  );

  if (sent) {
    return (
      <div className="container-site max-w-lg py-10">
        <h1 className="dredge-title">обращение #{sent.id} принято</h1>
        <p className="mt-4 text-sm text-text-secondary">
          Спасибо! Тема: {sent.topic_label ?? sent.topic}. Мы читаем все обращения и отвечаем
          на указанный контакт{sent.email ? ` (${sent.email})` : ""}.
        </p>
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={() => setSent(null)} className="btn-ghost">
            Написать ещё
          </button>
          <Link href="/" className="btn-primary">
            К архиву
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="container-site max-w-lg py-10">
      <h1 className="dredge-title">обратная связь</h1>
      <p className="mt-2 text-sm text-text-secondary">
        Баги, идеи, вопросы по контенту и правам.{" "}
        {user ? `Ответим на ${user.email}.` : "Укажите email, если хотите получить ответ."}
      </p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        <div>
          <span className="font-mono text-[11px] uppercase tracking-wider text-text-muted">
            тема
          </span>
          <div className="mt-2 flex flex-wrap gap-2">
            {TOPICS.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setTopic(t.value)}
                title={t.hint}
                className={`filter-btn font-mono text-[11px] ${
                  topic === t.value ? "filter-btn-active" : ""
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex flex-col gap-1 text-xs text-text-secondary">
          Сообщение <span className="text-text-muted">({active.hint})</span>
          <textarea
            required
            minLength={MIN_MESSAGE}
            rows={7}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary"
            placeholder="Что случилось, что хотелось бы изменить, где именно (ссылка на страницу)"
          />
        </label>

        {!user ? (
          <label className="flex flex-col gap-1 text-xs text-text-secondary">
            Email для ответа (необязательно)
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded border border-line bg-ink-secondary px-3 py-2 text-sm text-text-primary outline-none focus:border-accent-primary"
              autoComplete="email"
            />
          </label>
        ) : null}

        {/* Ловушка для ботов: скрыта от людей, заполняют только спам-боты */}
        <label className="hidden" aria-hidden>
          Не заполняйте это поле
          <input
            tabIndex={-1}
            autoComplete="off"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </label>

        {error ? <p className="text-sm text-accent-danger">{error}</p> : null}

        <button
          type="submit"
          disabled={busy || message.trim().length < MIN_MESSAGE}
          className="btn-primary mt-1"
        >
          {busy ? "Отправляем…" : "Отправить обращение"}
        </button>
      </form>

      <p className="mt-6 text-xs leading-relaxed text-text-muted">
        Премиум-доступ включается вручную: отправьте заявку с темой «Премиум-доступ» — доступ
        выдадут вашему аккаунту. Статус и срок видны в{" "}
        <Link href="/profile" className="text-accent-primary hover:underline">
          профиле
        </Link>
        .
      </p>
    </div>
  );
}

