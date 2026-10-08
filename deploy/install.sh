#!/usr/bin/env bash
# Installe ou met à jour Don de soi sur un serveur Ubuntu (22.04 / 24.04, x86 ou ARM).
# À lancer en root :  sudo DONDESOI_DOMAIN=mon.domaine bash install.sh
# Sans DONDESOI_DOMAIN, une adresse gratuite <ip>.sslip.io est utilisée.
# Le script peut être relancé : il met à jour le code sans toucher aux données.
set -euo pipefail

REPO="${DONDESOI_REPO:-https://github.com/anemostec/dondesoi.git}"
BRANCH="${DONDESOI_BRANCH:-main}"
BASE=/opt/dondesoi

if [[ -z "${DONDESOI_DOMAIN:-}" ]]; then
    IP=$(curl -4 -fsS https://ifconfig.me)
    DONDESOI_DOMAIN="dondesoi.${IP//./-}.sslip.io"
fi
echo "==> Domaine : $DONDESOI_DOMAIN"

echo "==> Paquets"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3-venv python3-pip git curl debian-keyring debian-archive-keyring \
    apt-transport-https gnupg iptables-persistent
if ! command -v caddy >/dev/null; then
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -q && apt-get install -y -q caddy
fi

echo "==> Utilisateur et code"
id dondesoi >/dev/null 2>&1 || useradd --system --home "$BASE" --shell /usr/sbin/nologin dondesoi
mkdir -p "$BASE"
if [[ -d "$BASE/app/.git" ]]; then
    git -C "$BASE/app" fetch -q origin "$BRANCH" && git -C "$BASE/app" reset -q --hard "origin/$BRANCH"
else
    git clone -q --branch "$BRANCH" "$REPO" "$BASE/app"
fi
mkdir -p "$BASE/app/instance" "$BASE/models"
chown -R dondesoi:dondesoi "$BASE"

echo "==> Environnement Python"
[[ -d "$BASE/venv" ]] || sudo -u dondesoi python3 -m venv "$BASE/venv"
sudo -u dondesoi "$BASE/venv/bin/pip" install -q --upgrade pip
sudo -u dondesoi "$BASE/venv/bin/pip" install -q -r "$BASE/app/requirements.txt"

echo "==> Configuration"
if [[ ! -f /etc/dondesoi.env ]]; then
    cat > /etc/dondesoi.env <<CONF
DONDESOI_SECRET_KEY=dds-$(python3 -c 'import secrets; print(secrets.token_hex(32))')
DONDESOI_BEHIND_PROXY=true
DONDESOI_MODEL_CACHE=$BASE/models
DONDESOI_MAIL_BACKEND=console
DONDESOI_CONTACT_EMAIL=
# Pour envoyer de vrais e-mails :
# DONDESOI_MAIL_BACKEND=smtp
# DONDESOI_SMTP_HOST=smtp-relay.brevo.com
# DONDESOI_SMTP_PORT=587
# DONDESOI_SMTP_USER=...
# DONDESOI_SMTP_PASSWORD=...
# DONDESOI_MAIL_FROM="Don de soi <...>"
CONF
    chmod 640 /etc/dondesoi.env && chgrp dondesoi /etc/dondesoi.env
fi
grep -q '^DONDESOI_DOMAIN=' /etc/dondesoi.env \
    && sed -i "s|^DONDESOI_DOMAIN=.*|DONDESOI_DOMAIN=$DONDESOI_DOMAIN|" /etc/dondesoi.env \
    || echo "DONDESOI_DOMAIN=$DONDESOI_DOMAIN" >> /etc/dondesoi.env

echo "==> Base de données et modèle de sens"
cd "$BASE/app"
run_flask() {
    sudo -u dondesoi bash -c 'set -a; . /etc/dondesoi.env; set +a; exec "$0" --app dondesoi "$@"' \
        "$BASE/venv/bin/flask" "$@"
}
[[ -f instance/dondesoi.sqlite ]] || run_flask init-db
run_flask localiser   # migrations, coordonnées manquantes, téléchargement du modèle

echo "==> Services"
install -m 644 deploy/dondesoi.service /etc/systemd/system/dondesoi.service
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=DONDESOI_DOMAIN=%s\n' "$DONDESOI_DOMAIN" \
    > /etc/systemd/system/caddy.service.d/dondesoi.conf
systemctl daemon-reload
systemctl enable -q dondesoi caddy
systemctl restart dondesoi caddy

echo "==> Pare-feu (les images Oracle bloquent tout sauf SSH)"
for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
        || iptables -I INPUT 5 -p tcp --dport "$port" -m state --state NEW -j ACCEPT
done
netfilter-persistent save >/dev/null

echo "==> Terminé : https://$DONDESOI_DOMAIN"
