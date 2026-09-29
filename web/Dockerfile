# Operator console (Next.js standalone). Build: docker build -t gta7-web ./web
# NEXT_PUBLIC_* values are inlined at build time, so pass them as build args.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# npm install (not ci): a lockfile made on Windows misses some Linux-only optional deps
RUN npm install --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8090
ARG NEXT_PUBLIC_GRAFANA_URL=http://localhost:3001
ARG NEXT_PUBLIC_PROMETHEUS_URL=http://localhost:9090
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_GRAFANA_URL=$NEXT_PUBLIC_GRAFANA_URL \
    NEXT_PUBLIC_PROMETHEUS_URL=$NEXT_PUBLIC_PROMETHEUS_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
COPY --from=build --chown=app:app /app/public ./public
USER app
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
