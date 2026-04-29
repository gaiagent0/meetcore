FROM node:20-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:5167
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

RUN pnpm build

# ── Runner ────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

RUN addgroup -S meetcore && adduser -S meetcore -G meetcore

COPY --from=builder --chown=meetcore:meetcore /app/.next/standalone ./
COPY --from=builder --chown=meetcore:meetcore /app/.next/static ./.next/static
COPY --from=builder --chown=meetcore:meetcore /app/public ./public 2>/dev/null || true

USER meetcore

EXPOSE 3118

ENV PORT=3118 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
