# syntax=docker/dockerfile:1
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
# The browser calls the API on its own origin; nginx forwards /api to the backend.
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
# The base image lags the Alpine security fixes (CVE-2026-31789 in OpenSSL); take them at build time.
USER root
RUN apk upgrade --no-cache libcrypto3 libssl3
USER 101
# Rendered into conf.d/default.conf at start; only these two variables are substituted.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER='^(API_UPSTREAM|DNS_RESOLVER)$' API_UPSTREAM=http://api:8010 DNS_RESOLVER=127.0.0.11
COPY security.inc /etc/nginx/conf.d/security.inc
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
