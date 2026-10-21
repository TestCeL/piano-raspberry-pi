# Compilación (Debian 12) de sfizz 1.2.3: reproductor SFZ libre (sfizz_jack + sfizz_render).
#   arm64 (Raspberry Pi, emulado):  docker build --platform linux/arm64 --build-arg PLATAFORMA=linux/arm64 ...
#   amd64 (PC, nativo; solo para renderizar y medir niveles offline): --build-arg PLATAFORMA=linux/amd64
ARG PLATAFORMA=linux/arm64
FROM --platform=$PLATAFORMA debian:bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build pkg-config file ca-certificates curl patch \
      libjack-jackd2-dev \
 && rm -rf /var/lib/apt/lists/*

COPY patches/ /usr/local/share/sfizz-patches/
COPY build-in-container.sh /usr/local/bin/build-in-container.sh
RUN chmod +x /usr/local/bin/build-in-container.sh

ENTRYPOINT ["/usr/local/bin/build-in-container.sh"]
