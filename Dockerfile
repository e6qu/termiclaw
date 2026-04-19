# Matches harbor-framework/terminal-bench's ubuntu-24-04 base image,
# plus an ENTRYPOINT so the container idles for `docker exec`.
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y \
    tmux asciinema \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENTRYPOINT ["sleep", "infinity"]
