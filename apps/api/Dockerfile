# Multi-stage Dockerfile for Traductor Live API (Monorepo)
FROM node:22-alpine AS base
WORKDIR /app

# Install dependencies needed for build
COPY package.json package-lock.json ./
COPY apps/api/package.json ./apps/api/
COPY apps/mobile/package.json ./apps/mobile/
COPY packages/shared/package.json ./packages/shared/

RUN npm ci

# Builder stage
FROM base AS builder
WORKDIR /app

COPY packages/shared ./packages/shared
COPY apps/api ./apps/api
COPY tsconfig.json ./

RUN npm run build -w @traductor/api

# Runner stage
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000

# Security: Run as non-root user
USER node

# Copy dependencies and build output
COPY --chown=node:node --from=base /app/node_modules ./node_modules
COPY --chown=node:node --from=base /app/packages ./packages
COPY --chown=node:node --from=base /app/apps/api/package.json ./apps/api/package.json
COPY --chown=node:node --from=base /app/package.json ./package.json
COPY --chown=node:node --from=builder /app/apps/api/dist ./apps/api/dist

EXPOSE 3000

CMD ["node", "apps/api/dist/server.js"]
