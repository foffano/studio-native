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

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py auth.py captions.py secretbox.py store.py tiktok.py ./
COPY fonts/ ./fonts/
COPY --from=front /front/dist ./desktop/dist

# Usuario sem privilegio nenhum. O mesmo uid precisa ser o dono da pasta de
# dados no host (ver deploy/compose.yml).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin studio
USER 10001:10001

ENV PYTHONUNBUFFERED=1 \
    STUDIO_HOST=0.0.0.0 \
    STUDIO_PORT=5050 \
    STUDIO_DATA_DIR=/app/data \
    STUDIO_TMP_DIR=/app/data/tmp

# Tag da release (ex.: v1.5.3), passada pelo release.yml. O /api/health a
# informa, e o atualizador do prod-01 confere se a versao no ar e a esperada.
ARG APP_VERSION=""
ENV STUDIO_VERSION=${APP_VERSION}
LABEL org.opencontainers.image.version=${APP_VERSION}

EXPOSE 5050
CMD ["python", "app.py"]
