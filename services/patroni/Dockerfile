FROM docker.io/library/postgres:18-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc
RUN apt-get update && apt-get install -y --no-install-recommends python3-venv pgbackrest && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/patroni
COPY requirements.lock /tmp/requirements.lock
RUN /opt/patroni/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
RUN mkdir -p /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql && chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /run/postgresql
USER postgres
ENTRYPOINT []
CMD ["/opt/patroni/bin/patroni", "/etc/patroni.yml"]
