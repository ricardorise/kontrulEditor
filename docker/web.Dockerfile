FROM node:22-slim AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /web/dist /usr/share/nginx/html
# O nginx injeta o token da API: o navegador nunca o recebe. As variáveis são substituídas no start.
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
