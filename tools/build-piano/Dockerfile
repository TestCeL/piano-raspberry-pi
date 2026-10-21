# Entorno de compilación ARM64 idéntico en ABI a la Raspberry Pi (Debian 12 bookworm, glibc 2.36, GCC 12).
# Se ejecuta emulado (QEMU) en Docker Desktop: --platform linux/arm64.
FROM --platform=linux/arm64 debian:bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git ca-certificates pkg-config file \
      libasound2-dev libjack-jackd2-dev libcurl4-openssl-dev \
      libfreetype-dev libfontconfig1-dev \
      libx11-dev libxcomposite-dev libxcursor-dev libxext-dev \
      libxinerama-dev libxrandr-dev libxrender-dev libxi-dev \
      ladspa-sdk libegl-dev libglu1-mesa-dev mesa-common-dev libgl-dev \
      lv2-dev lilv-utils \
 && rm -rf /var/lib/apt/lists/*

COPY patches/ /usr/local/share/piano-patches/
COPY build-in-container.sh /usr/local/bin/build-in-container.sh
RUN chmod +x /usr/local/bin/build-in-container.sh

ENTRYPOINT ["/usr/local/bin/build-in-container.sh"]
