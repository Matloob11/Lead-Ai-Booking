#!/usr/bin/env bash
# Bind sheikhmahboob.com (+ www) to existing Frappe/ERPNext site on Hostinger VPS.
# Does NOT touch WhatsApp / n8n vhosts.
set -euo pipefail

SITE=187.127.123.235
DOMAIN=sheikhmahboob.com
BENCH=/home/frappe/frappe-bench
CONF=/etc/nginx/conf.d/sheikhmahboob-erp.conf

echo "=== 1) add domains + host_name ==="
sudo -u frappe bash -lc "cd '$BENCH' && bench setup add-domain $DOMAIN --site $SITE"
sudo -u frappe bash -lc "cd '$BENCH' && bench setup add-domain www.$DOMAIN --site $SITE"
sudo -u frappe bash -lc "cd '$BENCH' && bench --site $SITE set-config host_name https://$DOMAIN"
sudo -u frappe bash -lc "cd '$BENCH' && bench --site $SITE clear-cache" || true

echo "=== 2) nginx HTTP vhost (ERP only) ==="
cat > "$CONF" <<'NGINX'
# sheikhmahboob.com -> Frappe/ERPNext site 187.127.123.235 only
upstream sheikh_erp_frappe {
    server 127.0.0.1:8000 fail_timeout=0;
}
upstream sheikh_erp_socketio {
    server 127.0.0.1:9000 fail_timeout=0;
}

server {
    listen 80;
    listen [::]:80;
    server_name sheikhmahboob.com www.sheikhmahboob.com;

    root /home/frappe/frappe-bench/sites;

    proxy_buffer_size 128k;
    proxy_buffers 4 256k;
    proxy_busy_buffers_size 256k;

    client_max_body_size 50m;

    location /assets {
        try_files $uri =404;
        add_header Cache-Control "max-age=31536000";
    }

    location ~ ^/protected/(.*) {
        internal;
        try_files /187.127.123.235/$1 =404;
    }

    location /socket.io {
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Frappe-Site-Name 187.127.123.235;
        proxy_set_header Origin $scheme://$http_host;
        proxy_set_header Host $host;
        proxy_pass http://sheikh_erp_socketio;
    }

    location / {
        rewrite ^(.+)/$ $1 permanent;
        rewrite ^(.+)/index\.html$ $1 permanent;
        rewrite ^(.+)\.html$ $1 permanent;

        location ~* ^/files/.*.(htm|html|svg|xml) {
            add_header Content-disposition "attachment";
            try_files /187.127.123.235/public/$uri @sheikh_webserver;
        }

        try_files /187.127.123.235/public/$uri @sheikh_webserver;
    }

    location @sheikh_webserver {
        proxy_http_version 1.1;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Frappe-Site-Name 187.127.123.235;
        proxy_set_header Host $host;
        proxy_set_header X-Use-X-Accel-Redirect True;
        proxy_read_timeout 120;
        proxy_redirect off;
        proxy_pass http://sheikh_erp_frappe;
    }

    access_log /var/log/nginx/sheikhmahboob.access.log;
    error_log  /var/log/nginx/sheikhmahboob.error.log;
}
NGINX

nginx -t
systemctl reload nginx
echo nginx-http-ok

echo "=== 3) SSL certbot ==="
certbot --nginx -d sheikhmahboob.com -d www.sheikhmahboob.com \
  --non-interactive --agree-tos --register-unsafely-without-email --redirect

nginx -t
systemctl reload nginx

echo "=== 4) prove ==="
curl -sS -o /dev/null -w 'http=%{http_code} redirect=%{redirect_url}\n' "http://$DOMAIN/" || true
curl -sS -o /dev/null -w 'https=%{http_code}\n' "https://$DOMAIN/" || true
curl -sS -o /dev/null -w 'https_www=%{http_code}\n' "https://www.$DOMAIN/" || true
sudo -u frappe bash -lc "cd '$BENCH' && bench --site $SITE get-config host_name"
echo DONE
