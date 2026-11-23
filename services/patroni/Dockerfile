FROM docker.io/library/postgres:17-bookworm@sha256:837bed18782820fe967067cb5328b02b0d9992c1be9a37ee0c9c492cfc03af3b
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv pgbackrest && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/patroni
COPY requirements.lock /tmp/requirements.lock
RUN /opt/patroni/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
RUN mkdir -p /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql && chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql
USER postgres
ENTRYPOINT []
CMD ["/opt/patroni/bin/patroni", "/etc/patroni.yml"]
