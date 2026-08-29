# The nurse board.
#
# NEXT_PUBLIC_ATRIA_API is read by the browser, so Next inlines it at build
# time rather than reading it at runtime. It therefore has to be a build arg —
# setting it only under `environment:` in compose would leave the built bundle
# pointing at the default.
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
ARG NEXT_PUBLIC_ATRIA_API=http://localhost:8000
ENV NEXT_PUBLIC_ATRIA_API=$NEXT_PUBLIC_ATRIA_API
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json* ./
RUN npm ci --omit=dev
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["npm", "run", "start"]
