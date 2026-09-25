ARCH := $(shell uname -m)

ifeq ($(ARCH),x86_64)
    ARCH_CXXFLAGS = -march=native
    ARCH_BPF_INC = -I/usr/include/x86_64-linux-gnu
else ifeq ($(ARCH),aarch64)
    ARCH_CXXFLAGS = -march=armv8-a+crc+crypto
    ARCH_BPF_INC = -I/usr/include/aarch64-linux-gnu
else
    ARCH_CXXFLAGS =
    ARCH_BPF_INC =
endif

CXX = g++
CXXFLAGS = -std=c++20 -O3 $(ARCH_CXXFLAGS) -Wall -Wextra -pthread -Iinclude -I/usr/include/xdp
LDFLAGS = -lxdp -lbpf -lpthread -ldl

CLANG = clang
BPF_CFLAGS = -O2 -target bpf $(ARCH_BPF_INC) -I/usr/include


BIN_DIR = bin
SRC_DIR = src
NET_DIR = src/network

all: dirs $(BIN_DIR)/xdp_prog.o $(BIN_DIR)/af_xdp_core.o $(BIN_DIR)/engine_main

dirs:
	mkdir -p $(BIN_DIR)

$(BIN_DIR)/xdp_prog.o: $(NET_DIR)/xdp_prog.c
	$(CLANG) $(BPF_CFLAGS) -c $< -o $@

$(BIN_DIR)/af_xdp_core.o: $(NET_DIR)/af_xdp_core.cpp include/af_xdp_core.h include/solarflare_onload.h
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BIN_DIR)/engine_main: $(SRC_DIR)/engine_main.cpp $(BIN_DIR)/af_xdp_core.o include/order_book.h include/arbitrage_strategy.h include/benchmark.h include/cme_sbe.h include/itch50.h include/solarflare_onload.h
	$(CXX) $(CXXFLAGS) $(SRC_DIR)/engine_main.cpp $(BIN_DIR)/af_xdp_core.o $(LDFLAGS) -o $@

clean:
	rm -rf $(BIN_DIR)/*

.PHONY: all dirs clean
