#!/bin/sh
set -x
docker exec -i a7-n8n-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"' 
