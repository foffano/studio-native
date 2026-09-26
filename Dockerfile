# Imagem do Studio Native: o Flask serve a API e o front construido, na mesma
# origem e na mesma porta. Usada no prod-01 (ver deploy/compose.yml); quem roda
# direto numa VPS, sem Docker, usa tools/instalar-vps.sh.

# --- front (Vite) ------------------------------------------------------------
FROM node:24-bookworm-slim AS front
WORKDIR /front
# package.json e lock primeiro: enquanto eles nao mudam, o cache do npm ci vale.
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error
COPY desktop/ ./
RUN npm run build

# --- backend -----------------------------------------------------------------
FROM python:3.12-slim-bookworm

# ffmpeg/ffprobe: normalizacao do upload e render. As fontes nao sao enfeite --
# sem a de emoji, os emojis das frases somem; a DejaVu e a reserva do texto.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-color-emoji \
    fonts-dejavu-core \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Chromium do Playwright para a publicacao no TikTok Shop (seller.py), e o
# Xvfb: o servidor nao tem tela, e o navegador roda "com janela" numa tela
# virtual -- headless, o anti-robo do TikTok desconfia mais.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
  && python -m playwright install --with-deps chromium \
  && apt-get update \
  && apt-get install -y --no-install-recommends xvfb xauth \
  && rm -rf /var/lib/apt/lists/* \
  && chmod -R a+rX /ms-playwright

COPY app.py auth.py captions.py cdp_viewer.py secretbox.py seller.py store.py tiktok.py ./
COPY fonts/ ./fonts/
COPY --from=front /front/dist ./desktop/dist

# Usuario sem privilegio nenhum. O mesmo uid precisa ser o dono da pasta de
# dados no host (ver deploy/compose.yml).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin studio
USER 10001:10001

# HOME=/tmp: o Chromium grava cache em $HOME, e o usuario do container nao tem
# casa. TINI_KILL_PROCESS_GROUP: o tini (init: true no compose) repassa o
# SIGTERM ao grupo todo -- o xvfb-run, o app e o Chromium param juntos.
ENV PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=5050 \
    STUDIO_DATA_DIR=/app/data \
    STUDIO_TMP_DIR=/app/data/tmp \
    HOME=/tmp \
    TINI_KILL_PROCESS_GROUP=1

# Tag da release (ex.: v1.5.3), passada pelo release.yml. O /api/health a
# informa, e o atualizador do prod-01 confere se a versao no ar e a esperada.
ARG APP_VERSION=""
ENV STUDIO_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.version=${APP_VERSION}

EXPOSE 5050
# O xvfb-run da ao Chromium do TikTok Shop uma tela virtual (seller.py).
CMD ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24 -nolisten tcp", "python", "app.py"]
