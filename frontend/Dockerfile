FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS run
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S han && adduser -S han -G han -u 10001
COPY --from=build --chown=han:han /app/.next/standalone ./
COPY --from=build --chown=han:han /app/.next/static ./.next/static
COPY --from=build --chown=han:han /app/public ./public
USER han
EXPOSE 3000
# HAN_BACKEND_URL is read at request time by the /v1 proxy route (set it in the environment).
CMD ["node", "server.js"]
