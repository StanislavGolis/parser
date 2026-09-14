# ─────────────────────────────────────────────────────────────────
#  Образ фронтенда (Next.js).
#  Используется и для разработки (target dev, hot-reload), и для
#  продакшена (default target prod, standalone-runtime).
#  Сборка:  docker build -t parser-web .                  (prod)
#  Dev:     docker compose -f docker-compose.dev.yml up
# ─────────────────────────────────────────────────────────────────

FROM node:20-alpine AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

# ── Зависимости ────────────────────────────────────────────────
FROM base AS deps
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# ── Разработка (hot-reload) ─────────────────────────────────────
FROM deps AS dev
COPY . .
EXPOSE 3000
# В dev исходники и node_modules монтируются volume'ами, поэтому
# ставим зависимости при первом старте, если их ещё нет в volume.
CMD ["sh", "-c", "if [ ! -d node_modules ] || [ -z \"$(ls -A node_modules | head -1)\" ]; then npm install; fi && npm run dev"]

# ── Продакшен-сборка (standalone) ──────────────────────────────
FROM deps AS build
# Режим сайта (Dredger 2.0). В middleware Next переменные запекаются на этапе
# сборки, поэтому значение обязано попасть сюда, а не только в runtime-env.
ARG SITE_MODE=public
ENV SITE_MODE=$SITE_MODE
COPY . .
RUN npm run build

FROM node:20-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
