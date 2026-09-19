"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiSend } from "@/lib/api";
import { readAdminEmail, useAdminToken } from "@/lib/adminAuth";
import { formatNumber, formatUtc } from "@/lib/format";
import type { AdminAuditList, AdminUser, AdminUserCard, AdminUserList } from "@/lib/types";

const FILTERS = [
  { value: "all", label: "Все" },
  { value: "premium", label: "Премиум" },
  { value: "without-premium", label: "Без подписки" },
  { value: "blocked", label: "Заблокированные" },
  { value: "admins", label: "Админы" },
];

const SORTS = [
  { value: "created", label: "по регистрации" },
  { value: "last_seen", label: "по последнему входу" },
  { value: "marks", label: "по меткам" },
  { value: "email", label: "по аккаунту" },
];

const PREMIUM_DAYS = [
  { days: 7, label: "7 дней" },
  { days: 30, label: "30 дней" },
  { days: 365, label: "год" },
];

function errText(err: unknown): string {
  if (err instanceof ApiError && err.detail) return err.detail;
  return err instanceof Error ? err.message : "Ошибка";
}

/** Строка «подпись — значение» в карточке: подпись приглушена, значение не переносится. */
function CardRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="shrink-0 text-text-muted">{label}</span>
      <span
        className={`min-w-0 truncate text-right text-text-secondary ${mono ? "font-mono" : ""}`}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

/** Управление пользователями: список, карточка, действия, журнал админов. */
export default function AdminUsersPanel() {
  const { token } = useAdminToken();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("created");
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<AdminUserList | null>(null);
  const [card, setCard] = useState<AdminUserCard | null>(null);
  const [audit, setAudit] = useState<AdminAuditList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadList = useCallback(
    async (t: string, p: number, f: string, s: string, q: string) => {
      const params = new URLSearchParams({
        page: String(p),
        per_page: "25",
        filter: f,
        sort: s,
      });
      if (q.trim()) params.set("q", q.trim());
      try {
        setList(await apiSend<AdminUserList>(`/api/v1/admin/users?${params}`, { token: t }));
      } catch (err) {
        setError(errText(err));
      }
    },
    [],
  );

  const loadCard = useCallback(async (t: string, id: number) => {
    try {
      setCard(await apiSend<AdminUserCard>(`/api/v1/admin/users/${id}`, { token: t }));
    } catch (err) {
      setError(errText(err));
    }
  }, []);

  const loadAudit = useCallback(async (t: string) => {
    try {
      setAudit(await apiSend<AdminAuditList>("/api/v1/admin/audit?limit=40", { token: t }));
    } catch {
      /* журнал не критичен */
    }
  }, []);

  useEffect(() => {
    if (token) void loadList(token, page, filter, sort, applied);
  }, [token, page, filter, sort, applied, loadList]);

  useEffect(() => {
    if (token) void loadAudit(token);
  }, [token, loadAudit]);

  /** Действие над аккаунтом: в журнал пишется email админа из `X-Admin-Actor`. */
  const act = useCallback(
    async (
      path: string,
      body: unknown,
      successMessage: string,
      method: "POST" | "DELETE" = "POST",
    ) => {
      if (!token) return;
      setBusy(true);
      setError(null);
      setNotice(null);
      try {
        await apiSend<Record<string, unknown>>(path, {
          method,
          body: method === "DELETE" ? undefined : body ?? {},
          token,
          headers: { "X-Admin-Actor": readAdminEmail() || "admin-token" },
        });
        setNotice(successMessage);
        setCard(null);
        await loadList(token, page, filter, sort, applied);
        await loadAudit(token);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [token, page, filter, sort, applied, loadList, loadAudit],
  );

  const openCard = useCallback(
    (user: AdminUser) => {
      setNotice(null);
      if (token) void loadCard(token, user.id);
    },
    [token, loadCard],
  );

  const totalPages = list ? Math.max(1, Math.ceil(list.total / list.per_page)) : 1;

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-xl font-bold">Управление пользователями</h2>
        <p className="mt-0.5 text-xs text-text-secondary">
          Аккаунты, подписки, блокировки и след сессий. IP показывается только хешем,
          каждое действие администратора попадает в журнал.
        </p>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => {
              setFilter(item.value);
              setPage(1);
            }}
            className={`filter-btn font-mono text-[11px] ${
              filter === item.value ? "filter-btn-active" : ""
            }`}
          >
            {item.label}
          </button>
        ))}
        <span className="mx-1 h-4 w-px bg-line" />
        <select
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            setPage(1);
          }}
          className="rounded border border-line bg-ink-secondary px-2 py-1 text-xs text-text-primary outline-none"
        >
          {SORTS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(query);
            setPage(1);
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="email, @ник или Telegram ID"
            className="rounded border border-line bg-ink-secondary px-2 py-1 text-xs text-text-primary outline-none placeholder:text-text-muted"
          />
          <button type="submit" className="btn-ghost px-2.5 py-1 text-xs">
            Найти
          </button>
          {applied ? (
            <button
              type="button"
              className="btn-ghost px-2.5 py-1 text-xs"
              onClick={() => {
                setQuery("");
                setApplied("");
                setPage(1);
              }}
            >
              Сброс
            </button>
          ) : null}
        </form>
        <span className="ml-auto font-mono text-[11px] text-text-muted">
          {list ? `${formatNumber(list.total)} аккаунтов` : "загружаем…"}
        </span>
      </div>

      {notice ? (
        <p className="mb-3 rounded border border-accent-primary/40 bg-accent-primary/10 px-3 py-2 text-xs text-text-primary">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="mb-3 rounded border border-accent-danger/40 bg-accent-danger/10 px-3 py-2 text-xs text-accent-danger">
          {error}
        </p>
      ) : null}

      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full min-w-[940px] text-xs">
          <thead className="bg-ink-tertiary/60 font-mono text-[10px] uppercase tracking-wider text-text-muted">
            <tr>
              <th className="px-3 py-2 text-left">аккаунт</th>
              <th className="px-3 py-2 text-left">регистрация</th>
              <th className="px-3 py-2 text-left">последний вход</th>
              <th className="px-3 py-2 text-left">премиум</th>
              <th className="px-3 py-2 text-right">метки</th>
              <th className="px-3 py-2 text-right">просм./скач.</th>
              <th className="px-3 py-2 text-right">сессии</th>
              <th className="px-3 py-2 text-left">статус</th>
              <th className="px-3 py-2 text-right">карточка</th>
            </tr>
          </thead>
          <tbody>
            {(list?.items ?? []).map((user) => (
              <tr
                key={user.id}
                className={`border-t border-line transition-colors hover:bg-ink-secondary/40 ${
                  card?.id === user.id ? "bg-ink-secondary/60" : ""
                }`}
              >
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => openCard(user)}
                    className="text-left text-text-primary hover:text-accent-primary"
                  >
                    {user.display_name}
                  </button>
                  {user.telegram_id ? <span className="badge badge-muted ml-2">TG</span> : null}
                  {user.is_admin ? <span className="badge badge-warn ml-2">admin</span> : null}
                  {/* Вторая строка: чем ещё опознать аккаунт (почта и/или Telegram ID) */}
                  {user.email && user.display_name !== user.email ? (
                    <span className="mt-0.5 block font-mono text-[10px] text-text-muted">
                      {user.email}
                    </span>
                  ) : null}
                  {user.telegram_id ? (
                    <span className="mt-0.5 block font-mono text-[10px] text-text-muted">
                      id {user.telegram_id}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-text-muted">
                  {user.created_at ? formatUtc(user.created_at) : "—"}
                </td>
                <td className="px-3 py-2 text-text-muted">
                  {user.last_seen_at ? formatUtc(user.last_seen_at) : "не заходил"}
                </td>
                <td className="px-3 py-2">
                  {user.premium_active ? (
                    <span className="text-accent-secondary">
                      {user.premium_until ? `до ${formatUtc(user.premium_until)}` : "активен"}
                    </span>
                  ) : (
                    <span className="text-text-muted">нет</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatNumber(user.marks_count)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatNumber(user.views_count)} / {formatNumber(user.downloads_count)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatNumber(user.sessions_active)}
                </td>
                <td className="px-3 py-2">
                  {user.is_active ? (
                    <span className="text-text-secondary">активен</span>
                  ) : (
                    <span className="text-accent-danger">заблокирован</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => openCard(user)}
                    className="btn-ghost px-2 py-0.5 text-[11px]"
                    title="Открыть карточку: сессии, метки, скачивания, аудит"
                  >
                    статистика
                  </button>
                </td>
              </tr>
            ))}
            {list && list.items.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-text-muted">
                  ничего не найдено
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {list && list.total > list.per_page ? (
        <div className="mt-3 flex items-center justify-center gap-3 text-xs">
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            ← назад
          </button>
          <span className="font-mono text-text-muted">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            className="btn-ghost px-3 py-1.5 text-xs"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            вперёд →
          </button>
        </div>
      ) : null}

      {card ? (
        <div className="mt-4 rounded border border-line bg-ink-secondary/40 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold">{card.display_name}</h3>
              <p className="mt-0.5 font-mono text-[11px] text-text-muted">
                id {card.id}
                {card.email ? ` · ${card.email}` : ""}
                {card.telegram_id ? ` · Telegram ${card.telegram_id}` : ""}
                {card.telegram_username ? ` · @${card.telegram_username}` : ""} · регистрация{" "}
                {card.created_at ? formatUtc(card.created_at) : "—"} · последний вход{" "}
                {card.last_seen_at ? formatUtc(card.last_seen_at) : "не заходил"}
                {card.is_admin ? " · админ" : ""}
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                меток {formatNumber(card.marks_count)} · просмотров {formatNumber(card.views_count)} ·
                скачиваний {formatNumber(card.downloads_count)} · активных сессий{" "}
                {formatNumber(card.sessions_active)}
                {card.premium_active
                  ? ` · премиум до ${card.premium_until ? formatUtc(card.premium_until) : "—"}`
                  : " · премиума нет"}
              </p>
            </div>
            <button
              type="button"
              className="btn-ghost px-3 py-1.5 text-xs"
              onClick={() => setCard(null)}
            >
              Закрыть
            </button>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
              премиум:
            </span>
            {PREMIUM_DAYS.map((period) => (
              <button
                key={period.days}
                type="button"
                disabled={busy}
                className="btn-ghost px-2.5 py-1 text-xs"
                onClick={() =>
                  void act(
                    `/api/v1/admin/users/${card.id}/premium`,
                    { days: period.days },
                    `Премиум выдан на ${period.label}`,
                  )
                }
              >
                +{period.label}
              </button>
            ))}
            <button
              type="button"
              disabled={busy}
              className="btn-ghost px-2.5 py-1 text-xs"
              onClick={() =>
                void act(`/api/v1/admin/users/${card.id}/premium`, { days: null }, "Премиум снят")
              }
            >
              снять
            </button>
            <span className="mx-1 h-4 w-px bg-line" />
            <button
              type="button"
              disabled={busy}
              className="btn-ghost px-2.5 py-1 text-xs"
              onClick={() =>
                void act(
                  `/api/v1/admin/users/${card.id}/active`,
                  { is_active: !card.is_active },
                  card.is_active ? "Аккаунт заблокирован" : "Аккаунт разблокирован",
                )
              }
            >
              {card.is_active ? "заблокировать" : "разблокировать"}
            </button>
            <button
              type="button"
              disabled={busy}
              className="btn-ghost px-2.5 py-1 text-xs"
              onClick={() =>
                void act(`/api/v1/admin/users/${card.id}/sessions/revoke`, {}, "Сессии сняты")
              }
            >
              выйти со всех устройств
            </button>
            <button
              type="button"
              disabled={busy}
              className="btn-ghost px-2.5 py-1 text-xs"
              onClick={() =>
                void act(
                  `/api/v1/admin/users/${card.id}/reset-link`,
                  {},
                  "Ссылка смены пароля создана (письмо ушло, если почта настроена)",
                )
              }
            >
              ссылка смены пароля
            </button>
            {!card.is_admin ? (
              <button
                type="button"
                disabled={busy}
                className="rounded border border-accent-danger/40 px-2.5 py-1 text-xs text-accent-danger transition-colors hover:bg-accent-danger/15 disabled:opacity-50"
                onClick={() => {
                  if (
                    window.confirm(
                      `Удалить аккаунт ${card.email}? Метки и сессии удалятся, действие необратимо.`,
                    )
                  ) {
                    void act(`/api/v1/admin/users/${card.id}`, null, "Аккаунт удалён", "DELETE");
                  }
                }}
              >
                удалить аккаунт
              </button>
            ) : null}
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
            <div className="rounded border border-line p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                откуда пришёл
              </div>
              <div className="mt-2 flex flex-col gap-1 text-[11px]">
                <CardRow
                  label="источник"
                  value={card.source.referrer ?? "прямой заход"}
                />
                <CardRow label="utm" value={card.source.utm ?? "—"} />
                <CardRow
                  label="первый заход"
                  value={
                    card.source.first_hit_at
                      ? formatUtc(card.source.first_hit_at)
                      : "в аналитике не отмечен"
                  }
                />
                <CardRow
                  label="устройство"
                  value={
                    [card.source.device, card.source.browser].filter(Boolean).join(" · ") || "—"
                  }
                />
                <CardRow
                  label="ссылки входа"
                  value={`выдано ${card.source.links.issued} · использовано ${card.source.links.used}`}
                />
                <CardRow
                  label="последняя"
                  value={
                    card.source.links.last_used
                      ? `вход ${formatUtc(card.source.links.last_used)}`
                      : card.source.links.last_issued
                        ? `выдана ${formatUtc(card.source.links.last_issued)}, не открыта`
                        : "—"
                  }
                />
                <CardRow
                  label="браузеры"
                  value={`${formatNumber(card.source.sessions)} сессий · ${formatNumber(
                    card.source.anonymous_sessions,
                  )} начинали до входа`}
                />
                <CardRow
                  label="ip (хеш)"
                  value={card.source.ip_hash ? card.source.ip_hash.slice(0, 12) : "—"}
                  mono
                />
              </div>
            </div>

            <div className="rounded border border-line p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                сессии (последние 20)
              </div>
              {card.sessions.length === 0 ? (
                <p className="mt-2 text-xs text-text-muted">сессий нет</p>
              ) : (
                <div className="mt-2 flex flex-col gap-2">
                  {card.sessions.map((item) => (
                    <div key={item.id} className="text-[11px]">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className={item.active ? "text-text-secondary" : "text-text-muted"}>
                          {item.created_at ? formatUtc(item.created_at) : "—"}
                          {item.active ? " · активна" : " · истекла"}
                        </span>
                        <span className="font-mono text-text-muted">
                          ip {(item.ip_hash ?? "—").slice(0, 12)}
                        </span>
                      </div>
                      <div
                        className="truncate text-[10px] text-text-muted"
                        title={item.user_agent ?? ""}
                      >
                        {item.user_agent ?? "без User-Agent"} · был(а):{" "}
                        {item.last_seen_at ? formatUtc(item.last_seen_at) : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded border border-line p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                последние метки
              </div>
              {card.marks.length === 0 ? (
                <p className="mt-2 text-xs text-text-muted">меток нет</p>
              ) : (
                <div className="mt-2 flex flex-col gap-1">
                  {card.marks.map((mark) => (
                    <div
                      key={`${mark.media_id}-${mark.at}`}
                      className="flex items-baseline justify-between gap-2 text-[11px]"
                    >
                      <Link
                        href={`/media/${mark.media_id}`}
                        className="min-w-0 truncate text-text-secondary hover:text-accent-primary"
                        title={mark.name}
                      >
                        /{mark.board} · {mark.name}
                      </Link>
                      <span className="shrink-0 font-mono text-text-muted">
                        {mark.at ? formatUtc(mark.at) : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded border border-line p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                последние скачивания
              </div>
              {card.downloads.length === 0 ? (
                <p className="mt-2 text-xs text-text-muted">скачиваний нет</p>
              ) : (
                <div className="mt-2 flex flex-col gap-1">
                  {card.downloads.map((item) => (
                    <div
                      key={`${item.media_id}-${item.at}`}
                      className="flex items-baseline justify-between gap-2 text-[11px]"
                    >
                      <Link
                        href={`/media/${item.media_id}`}
                        className="min-w-0 truncate text-text-secondary hover:text-accent-primary"
                        title={item.name}
                      >
                        {item.name}
                      </Link>
                      <span className="shrink-0 font-mono text-text-muted">
                        {item.at ? formatUtc(item.at) : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded border border-line p-3">
              <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
                журнал по этому аккаунту
              </div>
              {card.audit.length === 0 ? (
                <p className="mt-2 text-xs text-text-muted">записей нет</p>
              ) : (
                <div className="mt-2 flex flex-col gap-1">
                  {card.audit.map((item, idx) => (
                    <div key={`${item.at}-${idx}`} className="text-[11px] text-text-muted">
                      <span className="font-mono">{item.at ? formatUtc(item.at) : "—"}</span>{" "}
                      <span className="text-accent-secondary">{item.action}</span>{" "}
                      <span>{item.details ?? ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {audit && audit.items.length > 0 ? (
        <div className="mt-5 rounded border border-line bg-ink-secondary/40 p-3">
          <div className="font-mono text-[10px] uppercase tracking-wider text-text-muted">
            журнал действий администраторов (последние {audit.items.length})
          </div>
          <div className="mt-2 flex flex-col gap-1">
            {audit.items.map((item, idx) => (
              <div
                key={`${item.at}-${idx}`}
                className="flex flex-wrap items-baseline gap-2 text-[11px]"
              >
                <span className="font-mono text-text-muted">
                  {item.at ? formatUtc(item.at) : "—"}
                </span>
                <span className="text-text-secondary">{item.actor ?? "admin-token"}</span>
                <span className="font-mono text-accent-secondary">{item.action}</span>
                <span className="text-text-muted">{item.details ?? item.target ?? ""}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
