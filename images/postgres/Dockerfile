FROM docker.io/library/postgres:16-alpine3.24@sha256:f4610795587492cd4fb887c2dc3de301b813278bb6f616992061141b5f15ac36
# Run as postgres from the outset: upstream supports arbitrary non-root users,
# so its vulnerable Go-based root-to-postgres helper is unnecessary.
RUN rm -f /usr/local/bin/gosu /usr/local/bin/su-exec \
    && mkdir -p /backups \
    && chown postgres:postgres /backups
USER postgres
