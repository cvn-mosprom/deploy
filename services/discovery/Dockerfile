FROM docker.io/library/python:3.15-alpine3.24@sha256:d44b1254cb92329418d164b22b20d86bbd3869d48e80e09e476531a409a728bb
WORKDIR /app
COPY server.py ./server.py
USER 10003:10003
EXPOSE 8080
CMD ["python", "server.py"]
