FROM docker.io/library/python:3.12-alpine3.24@sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d
WORKDIR /app
COPY server.py ./server.py
USER 10003:10003
EXPOSE 8080
CMD ["python", "server.py"]
