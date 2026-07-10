# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# ── Production stage (Nginx) ──────────────────────────────────────────────────
FROM nginx:1.27-alpine AS production

# Remove default Nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy built React app
COPY --from=build /app/dist /usr/share/nginx/html

# Nginx config: serve SPA with history-API fallback, proxy /api to backend
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/api/v1/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
