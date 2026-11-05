#!/usr/bin/env bash
# Build a zip to upload to cPanel hosting: the Django backend plus the web app already built
# for the given URL prefix, and a site.env with a fresh secret key.
#   scripts/make-cpanel-bundle.sh /Betewubet www.eruditeafrica.net
set -euo pipefail
PREFIX="${1:-/Betewubet}"
DOMAIN="${2:-www.eruditeafrica.net}"
BARE="${DOMAIN#www.}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist-cpanel"
STAGE="$OUT/betewubet-erp"

rm -rf "$OUT" && mkdir -p "$STAGE/frontend"
(cd "$ROOT/frontend" && npm ci --silent && VITE_APP_ROOT="$PREFIX" npx vite build --logLevel warn)
cp -r "$ROOT/frontend/dist" "$STAGE/frontend/dist"
rsync -a --exclude '__pycache__' --exclude '*.sqlite3' --exclude 'staticfiles' --exclude '.pytest_cache' \
  --exclude 'FIRST_LOGIN.txt' "$ROOT/backend/" "$STAGE/backend/"
SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
cat > "$STAGE/site.env" <<ENV
# Settings for the Betewubet ERP on cPanel. Change the DATABASE_URL line, nothing else is needed.
# DATABASE_URL=mysql://DATABASE_USER:PASSWORD@localhost:3306/DATABASE_NAME
DATABASE_URL=mysql://CHANGE_USER:CHANGE_PASSWORD@localhost:3306/CHANGE_DATABASE
URL_PREFIX=$PREFIX
ALLOWED_HOSTS=$DOMAIN,$BARE
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://$BARE
DEBUG=false
HTTPS=true
SECRET_KEY=$SECRET
ENV
(cd "$OUT" && zip -qr betewubet-erp-cpanel.zip betewubet-erp)
# For updating a running site: no site.env (keeps the live settings) and no passenger_wsgi.py
# (cPanel manages that file).
(cd "$OUT" && zip -qr betewubet-erp-update.zip betewubet-erp -x 'betewubet-erp/site.env' 'betewubet-erp/backend/passenger_wsgi.py')
echo "$OUT/betewubet-erp-cpanel.zip"
echo "$OUT/betewubet-erp-update.zip"
