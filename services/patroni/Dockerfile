FROM docker.io/library/postgres:16-bookworm@sha256:d81f7b51697014367236d07ec58b54153fc28f828b72bf247fe5c7487520bcb0
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv pgbackrest && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/patroni
COPY requirements.lock /tmp/requirements.lock
RUN /opt/patroni/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
RUN mkdir -p /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql && chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql
USER postgres
ENTRYPOINT []
CMD ["/opt/patroni/bin/patroni", "/etc/patroni.yml"]
