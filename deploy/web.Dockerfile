# The web app (React build) served by Caddy, which also terminates HTTPS and
# proxies /api to the backend. Built from the repository root:
#   docker build -f deploy/web.Dockerfile .
FROM node:22.23.3-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM caddy:2.11.7-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
