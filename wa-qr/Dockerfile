# whatsapp-web.js drives a real Chromium, so the image needs a browser and the
# fonts and libraries it refuses to start without. Puppeteer's own bundled
# download is skipped in favour of the distro package: it is patched by Debian
# and does not have to be re-fetched on every build.
FROM node:20-bookworm-slim

ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    NODE_ENV=production

# chromium-sandbox is not optional here. The `chromium` package alone does not
# pull in the SUID sandbox helper under --no-install-recommends, and without it
# Chromium refuses to start at all as a non-root user: "No usable sandbox!".
# The usual answer found online is --no-sandbox, which is the opposite of what
# is wanted — this process renders whatever a stranger sends.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      chromium-sandbox \
      fonts-liberation fonts-noto-color-emoji \
      ca-certificates \
      libnss3 libatk-bridge2.0-0 libgtk-3-0 libasound2 libgbm1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev

COPY . .

# Chromium will not run as root without --no-sandbox, and running a browser
# that renders whatever a stranger sends as root is not worth the shortcut.
RUN useradd --uid 10001 --create-home waqr && mkdir -p /data && chown -R waqr /data /app
USER waqr

EXPOSE 8300
CMD ["node", "src/index.js"]
