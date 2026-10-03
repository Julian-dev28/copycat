# Built from the repo root (see docker-compose.yml: context ".", dockerfile services/web/Dockerfile)
# so the root .dockerignore applies.
FROM node:22-alpine AS deps
WORKDIR /app
COPY services/web/package.json services/web/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
# Next inlines NEXT_PUBLIC_* at build time: the browser calls this URL directly.
ARG NEXT_PUBLIC_COPYCAT_API=http://localhost:8787
ENV NEXT_PUBLIC_COPYCAT_API=$NEXT_PUBLIC_COPYCAT_API \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY services/web/ ./
RUN mkdir -p public && npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
