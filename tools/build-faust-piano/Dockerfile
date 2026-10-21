# Compilación ARM64 (Debian 12) del piano de guía de ondas conmutado de Faust/STK como plugin LV2 polifónico.
FROM --platform=linux/arm64 debian:bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      faust g++ make patch file pkg-config lv2-dev libboost-dev lilv-utils \
 && rm -rf /var/lib/apt/lists/*

COPY patches/ /usr/local/share/stkpiano-patches/
COPY build-in-container.sh /usr/local/bin/build-in-container.sh
RUN chmod +x /usr/local/bin/build-in-container.sh

ENTRYPOINT ["/usr/local/bin/build-in-container.sh"]
