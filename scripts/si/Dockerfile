FROM debian:bookworm-slim
RUN apt-get -o Acquire::http::Proxy="${http_proxy:-$HTTP_PROXY}" update && apt-get -o Acquire::http::Proxy="${http_proxy:-$HTTP_PROXY}" install -y --no-install-recommends python3-openems python3-numpy python3-scipy python3-shapely python3-matplotlib ngspice && rm -rf /var/lib/apt/lists/*
WORKDIR /case
