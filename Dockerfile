# SynapticAMS — multi-stage Docker image
# Builds natively for the host platform (arm64 on Apple Silicon, amd64 on Linux servers).
# No --platform override: Docker BuildKit picks the host arch automatically.
#
# Stages:
#   1. openvaf-builder  — compile OpenVAF (Verilog-AMS → OSDI compiler) from Rust
#   2. ngspice-builder  — compile ngspice 46 with --with-osdi from source
#   3. runtime          — slim Ubuntu 22.04 with both binaries + Python deps

# ── Stage 1: Build OpenVAF ────────────────────────────────────────────────
FROM ubuntu:22.04 AS openvaf-builder

ENV DEBIAN_FRONTEND=noninteractive

# Bootstrap: curl + gnupg to add the LLVM apt repo key
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Add LLVM 14 from apt.llvm.org.
# OpenVAF v22.12.0's OpenVafWrapper.cpp uses LLVM 14 API:
#   - 5-param link(args, stdout, stderr, exitEarly, disableOutput) [LLVM 14+]
#   - CommonLinkerContext::destroy() [LLVM 14+]
# Cargo.toml says links="llvm-13" (outdated) but OpenVafWrapper.cpp targets LLVM 14.
RUN curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/apt.llvm.org.gpg \
    && echo "deb https://apt.llvm.org/jammy/ llvm-toolchain-jammy-14 main" \
        > /etc/apt/sources.list.d/llvm.list

# Install complete LLVM 14 toolchain:
#   llvm-14-dev     — LLVM headers + static libs
#   clang-14        — C compiler (includes clang-cl-14)
#   lld-14          — LLD linker binaries (ld.lld-14, lld-link-14, llvm-dlltool-14)
#   liblld-14-dev   — LLD C++ headers (lld/Common/Driver.h for OpenVafWrapper.cpp)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake pkg-config git \
        llvm-14-dev clang-14 lld-14 liblld-14-dev \
        libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/clang-14        /usr/bin/clang \
    && ln -sf /usr/bin/lld-14          /usr/bin/lld \
    && ln -sf /usr/bin/ld.lld-14       /usr/bin/ld.lld \
    && ln -sf /usr/bin/lld-link-14     /usr/bin/lld-link \
    && printf '#!/bin/sh\nexec /usr/bin/clang-14 --driver-mode=cl "$@"\n' > /usr/bin/clang-cl \
    && chmod +x /usr/bin/clang-cl \
    && ln -sf /usr/bin/llvm-dlltool-14 /usr/bin/llvm-dlltool \
    && ln -sf /usr/bin/llvm-lib-14     /usr/bin/llvm-lib \
    && ln -sf /usr/bin/llvm-ar-14      /usr/bin/llvm-ar \
    && ln -sf /usr/bin/llvm-nm-14      /usr/bin/llvm-nm \
    && ln -sf /usr/bin/llvm-ranlib-14  /usr/bin/llvm-ranlib

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --default-toolchain stable --profile minimal
ENV PATH="/root/.cargo/bin:${PATH}"

# OpenVAF build.rs reads $LLVM_CONFIG; llvm-14-dev installs llvm-config-14.
# libLLVM-14.so on Ubuntu apt.llvm.org omits optional backends (AMDGPU, AVR,
# BPF, Hexagon, Lanai, Mips, MSP430, PowerPC, RISCV, Sparc, SystemZ, VE,
# WebAssembly, M68k). OpenVAF's Driver.cpp calls InitializeAllTargetInfos()
# which references all backends. Provide no-op stubs so the linker is happy;
# OpenVAF only generates native OSDI code so unregistered backends are fine.
# getPollyPluginInfo() is also needed: LLVM apt build has Polly linked in.
# Build the backend stub archive and create empty Polly archives.
# llvm-config --libs returns -lPolly -lPollyISL (apt.llvm.org built with Polly);
# libpolly-14-dev conflicts so we stub them — libPolly.a stays empty because
# getPollyPluginInfo() is provided by libllvm_backend_stubs.a instead.
# Compile backend stubs (all LLVMInitialize* no-ops for targets missing from
# libLLVM-14.so) and place them where RUSTFLAGS can force-link them.
# getPollyPluginInfo() goes into libPolly.a (cargo:rustc-link-lib=static=Polly
# resolves it there); keeping it separate avoids a duplicate-symbol error.
COPY llvm_backend_stubs.c /tmp/llvm_backend_stubs.c
# Build two link-time inputs injected via RUSTFLAGS:
#   polly_stub.o          — direct object file (always included, no archive lazy-resolution)
#                           provides getPollyPluginInfo() called from LTOBackend.cpp.o inside
#                           libllvm.rlib; -lPolly does NOT appear in cargo's link command so
#                           libPolly.a is never opened — only a direct .o guarantees inclusion.
#   libllvm_backend_stubs.a — static archive for LLVMInitialize* no-ops (archive is fine here
#                             because those symbols ARE referenced by Driver.cpp → always pulled in).
# libPolly.a / libPollyISL.a are left empty so that if -lPolly ever appears it resolves cleanly.
RUN clang-14 -O2 -c /tmp/llvm_backend_stubs.c -o /tmp/llvm_backend_stubs.o \
    && ar rcs /usr/local/lib/libllvm_backend_stubs.a /tmp/llvm_backend_stubs.o \
    && LIBDIR="$(/usr/bin/llvm-config-14 --libdir)" \
    && printf '#include <stdint.h>\nstruct PI{uint32_t v;const char*n,*ver;void(*cb)(void*);};static void noop(void*){}PI getPollyPluginInfo(){PI p;p.v=14;p.n="polly-stub";p.ver="14.0.0";p.cb=noop;return p;}\n' \
        > /tmp/polly_stub.cpp \
    && clang-14 -x c++ -O2 -c /tmp/polly_stub.cpp -o /usr/local/lib/polly_stub.o \
    && ar rcs "$LIBDIR/libPolly.a" \
    && ar rcs "$LIBDIR/libPollyISL.a"
ENV RUSTFLAGS="-C link-arg=/usr/local/lib/polly_stub.o -C link-arg=/usr/local/lib/libllvm_backend_stubs.a"
ENV LLVM_CONFIG=/usr/bin/llvm-config-14

# Clone OpenVAF at v22.12.0 — the confirmed available tag
RUN git clone --depth 1 --branch OpenVAF-v22.12.0 \
        https://github.com/pascalkuthe/OpenVAF.git /build/openvaf
WORKDIR /build/openvaf

# Patch Cargo.toml: update links="llvm-13" → "llvm-14" to match actual LLVM version
# (OpenVafWrapper.cpp uses LLVM 14 API; the Cargo.toml value is outdated)
RUN find . -name 'Cargo.toml' -exec sed -i 's/links = "llvm-13"/links = "llvm-14"/g' {} +

# Patch initialization.rs: on arm64 `c_char` is `u8` (unsigned), not `i8`.
# The original code casts `b"".as_ptr() as *const i8` which fails on arm64 because
# LLVMParseCommandLineOptions expects *const c_char = *const u8 on arm64.
# Replace with std::ptr::null() which is type-inferred and platform-neutral.
RUN sed -i \
    's|b""\.as_ptr() as \*const i8|std::ptr::null::<std::os::raw::c_char>()|' \
    openvaf/llvm/src/initialization.rs

# Cache Rust deps first (layer invalidated only when Cargo.lock changes)
RUN cargo fetch

# Full release build — this is the slow step (~20 min first time, cached after)
RUN cargo build --release --bin openvaf

RUN echo "==> OpenVAF build complete:" && \
    ls -lh target/release/openvaf && \
    ./target/release/openvaf --version

# ── Stage 2: Build ngspice 46 with OSDI support ───────────────────────────
FROM ubuntu:22.04 AS ngspice-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential autoconf automake libtool curl ca-certificates \
        libfftw3-dev libreadline-dev bison flex \
    && rm -rf /var/lib/apt/lists/*

ARG NGSPICE_VERSION=46

# SourceForge: the /download suffix triggers the mirror redirect
RUN curl -fsSL \
        "https://sourceforge.net/projects/ngspice/files/ng-spice-rework/${NGSPICE_VERSION}/ngspice-${NGSPICE_VERSION}.tar.gz/download" \
        -o /tmp/ngspice.tar.gz && \
    tar -xzf /tmp/ngspice.tar.gz -C /tmp/

WORKDIR /tmp/ngspice-${NGSPICE_VERSION}

RUN ./configure \
        --with-osdi \
        --enable-xspice \
        --disable-debug \
        --without-x \
        --prefix=/opt/ngspice \
        CFLAGS="-O2" && \
    make -j"$(nproc)" && \
    make install

RUN echo "==> ngspice OSDI build complete" && \
    /opt/ngspice/bin/ngspice --version 2>&1 | head -5 || true

# ── Stage 3: Runtime image ────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# OpenVAF links LLVM statically but dynamically needs libxml2 (LLVM IR parser dep).
# ngspice runtime deps: libfftw3-3, libreadline8 (built with --without-x so no X11)
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        libfftw3-3 \
        libreadline8 \
        libxml2 \
        libncurses6 \
        curl \
        jq \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

# ── OpenVAF binary ──────────────────────────────────────────────────────
COPY --from=openvaf-builder /build/openvaf/target/release/openvaf /usr/local/bin/openvaf
RUN chmod +x /usr/local/bin/openvaf

# ── ngspice (OSDI-enabled) ───────────────────────────────────────────────
COPY --from=ngspice-builder /opt/ngspice /opt/ngspice
RUN ln -sf /opt/ngspice/bin/ngspice /usr/local/bin/ngspice

# ngspice looks for its spinit file relative to its prefix; tell it where that is
ENV SPICE_LIB_DIR=/opt/ngspice/share/ngspice

# ── Sanity-check both tools are functional ───────────────────────────────
RUN openvaf --version
RUN printf 'smoke_test\nV1 in 0 dc 1\nR1 in 0 1k\n.dc V1 0 1 0.5\n.end\n' \
        > /tmp/smoke.cir && \
    /opt/ngspice/bin/ngspice -b /tmp/smoke.cir 2>&1 | head -8 && \
    rm /tmp/smoke.cir

# ── Python dependencies ──────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ── Application code ─────────────────────────────────────────────────────
WORKDIR /app
COPY . /app

ENV PYTHONPATH=/app

# ── Default entrypoint: run the SerDes system-level demo ─────────────────
# Prerequisites on the host before running:
#   ollama serve              (start local LLM server)
#   ollama pull qwen2.5-coder:7b
#
# Run with:
#   docker compose run demo
#
# Override Ollama URL (WSL2 plain Docker Engine):
#   OLLAMA_BASE_URL=http://172.x.x.x:11434 docker compose run demo
CMD ["bash", "examples/serdes_system_level_demo/run_system_level_demo.sh"]
