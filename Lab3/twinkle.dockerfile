# ===== Build stage =====
FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
      cmake \
      ca-certificates \
      build-essential \
      git \
      bison \
      flex \
      qtbase5-dev \
      qttools5-dev \
      qttools5-dev-tools \
      qtbase5-dev \
      qtdeclarative5-dev \
      libasound2-dev \
      libgsm1-dev \
      libsndfile1-dev \
      libspeex-dev \
      libspeexdsp-dev \
      libccrtp-dev \
      libxml2-dev \
      libmagic-dev \
      libreadline-dev \
      pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Clone Twinkle source (shallow for smaller image)
RUN git clone --depth 1 https://github.com/LubosD/twinkle.git .

# Build Twinkle
RUN mkdir build && cd build && cmake .. -Dexample_option=On && make install 
RUN mkdir /tmp/twinkle
