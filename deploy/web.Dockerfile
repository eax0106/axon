# The dashboard: built with Node 20, served as static files by nginx, which also proxies /api
# (HTTP and WebSocket) to the API so the browser has one origin and needs no CORS.
FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
COPY packages/contracts/package.json packages/contracts/
RUN pnpm install --frozen-lockfile --filter web...
COPY packages/contracts packages/contracts
COPY apps/web apps/web
RUN pnpm --filter web build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
