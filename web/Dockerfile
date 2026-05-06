# ── Build stage ────────────────────────────────────────────────────────────────
FROM node:22-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# API_URL is consumed at build time by next.config.ts rewrites() to set the
# server-side proxy target. In Docker the API is reachable by container name.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL

RUN npm run build

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# next build --output standalone copies the minimal server and its deps here.
COPY --from=builder /app/.next/standalone ./
# Static assets and public files must be copied separately.
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000

CMD ["node", "server.js"]
