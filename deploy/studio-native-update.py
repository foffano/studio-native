#!/usr/bin/env python3
"""Instala no prod-01 a ultima release estavel do Studio Native.

Roda pelo studio-native-update.timer (a cada 5 minutos), no mesmo padrao do
eco-native-update. A diferenca: a imagem ja vem pronta do GHCR, entao nada e
construido aqui -- quem sobe a versao nova, e volta sozinho para a anterior se
ela nao ficar saudavel, e o /srv/infra/scripts/deploy.sh.

Instalar (na VPS, a partir do repositorio):
  sudo install -m 755 deploy/studio-native-update.py /srv/infra/scripts/
  sudo install -m 644 deploy/studio-native-update.service deploy/studio-native-update.timer /etc/systemd/system/
  sudo systemctl daemon-reload && sudo systemctl enable --now studio-native-update.timer

Forcar uma versao (tambem serve para tentar de novo uma que falhou):
  sudo /srv/infra/scripts/studio-native-update.py --tag v1.5.3
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request

REPO = 'foffano/studio-native'
APP_NAME = 'studio-native'
APP = Path('/srv/apps/studio-native')
IMAGE = 'ghcr.io/foffano/studio-native'
DEPLOY = '/srv/infra/scripts/deploy.sh'
HEALTH = ('import urllib.request;print(urllib.request.urlopen('
          '"http://127.0.0.1:5050/api/health", timeout=10).read().decode())')


def version(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError(f'Tag de release invalida: {tag!r}')
    return tuple(map(int, tag[1:].split('.')))


def request(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'studio-native-updater'})
    return urllib.request.urlopen(req, timeout=60)


def run(*args, capture=False, check=True):
    return subprocess.run(args, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None)


def health():
    out = run('docker', 'compose', '--project-name', APP_NAME,
              '--project-directory', str(APP), '-f', str(APP / 'compose.yml'),
              'exec', '-T', 'web', 'python', '-c', HEALTH, capture=True)
    return json.loads(out.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tag', help='release especifica; tambem refaz uma que falhou')
    args = parser.parse_args()

    # Trava propria: o deploy.sh pega a .deploy.lock, e segura-la aqui faria
    # o deploy.sh desistir.
    with (APP / '.update.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Outra atualizacao esta rodando.')
            return

        endpoint = 'tags/' + args.tag if args.tag else 'latest'
        with request(f'https://api.github.com/repos/{REPO}/releases/{endpoint}') as response:
            release = json.load(response)
        tag = release['tag_name']
        version(tag)
        if release['draft'] or release['prerelease']:
            raise ValueError('So releases estaveis publicadas sao aceitas')

        current = re.search(r'^IMAGE_TAG=(.+)$', (APP / '.env').read_text(), re.M).group(1)
        if not args.tag and version(tag) <= version(current):
            print(f'Ja esta na versao atual: {current}.')
            return

        failed = APP / '.failed-release'
        if not args.tag and failed.exists() and failed.read_text().strip() == tag:
            print(f'{tag} falhou antes; veja o journal e tente de novo com --tag {tag}.')
            return

        # A release sai antes da imagem: o build do GitHub Actions leva alguns
        # minutos. Enquanto a imagem nao existe, so espera a proxima rodada.
        if run('docker', 'pull', '--quiet', f'{IMAGE}:{tag}', check=False).returncode:
            print(f'{tag}: imagem ainda nao publicada no GHCR; tento de novo depois.')
            return

        # Reiniciar no meio de uma geracao perde o video. Versoes ate a 1.5.2
        # nao informam "busy"; nelas nao ha como saber, e a troca segue.
        status = health()
        if status.get('busy'):
            print('Adiado: ha geracao, pre-processamento ou publicacao em andamento.')
            return

        # O compose.yml vem da propria release, entao mudancas nele chegam junto.
        with tempfile.TemporaryDirectory(prefix='studio-native-release-') as directory:
            os.chmod(directory, 0o755)
            compose = Path(directory) / 'compose.yml'
            raw = f'https://raw.githubusercontent.com/{REPO}/{tag}/deploy/compose.yml'
            with request(raw) as response:
                compose.write_bytes(response.read())
            os.chmod(compose, 0o644)
            env = dict(os.environ, GITHUB_ACTOR='release-updater')
            result = subprocess.run(
                ['runuser', '-u', 'deploy', '--', DEPLOY, APP_NAME, IMAGE, tag, str(compose)],
                env=env,
            )
        if result.returncode:
            failed.write_text(tag + '\n')
            raise SystemExit(f'deploy.sh falhou para {tag}; a versao anterior ficou no ar.')

        # A versao so passou a ser informada na 1.5.3.
        running = health().get('version')
        if running != tag and version(tag) >= (1, 5, 3):
            failed.write_text(tag + '\n')
            raise SystemExit(f'A versao no ar informa {running!r}, esperado {tag}.')
        failed.unlink(missing_ok=True)
        print(f'{time.strftime("%F %T")} {tag} instalada.')


if __name__ == '__main__':
    main()
