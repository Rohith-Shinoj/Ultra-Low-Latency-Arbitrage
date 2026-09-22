#pragma once

#include <cstdint>
#include <string>
#include <vector>
#include <memory>
#include <functional>
#include <chrono>

// Architecture-independent assembly hardware cycle counter
static inline uint64_t rdtsc_cycles() {
#if defined(__x86_64__) || defined(_M_X64)
    unsigned int lo, hi;
    __asm__ __volatile__ ("rdtsc" : "=a" (lo), "=d" (hi));
    return ((uint64_t)hi << 32) | lo;
#elif defined(__aarch64__)
    uint64_t val;
    __asm__ __volatile__ ("mrs %0, cntvct_el0" : "=r" (val));
    return val;
#else
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::high_resolution_clock::now().time_since_epoch()).count();
#endif
}

// Low-overhead packet representation
struct RawPacketDesc {
    const uint8_t* data;
    uint32_t len;
    uint16_t port;
    uint64_t ingress_cycles;
    uint64_t hardware_time_ns;
};

// High-performance AF_XDP / Kernel-Bypass Ingress Manager
class AFXDPSocket {
public:
    struct Config {
        std::string ifname = "veth1";
        uint32_t queue_id = 0;
        uint32_t num_frames = 4096;
        uint32_t frame_size = 2048;
        bool zero_copy = false; // Set to true for native driver zero-copy, false for SKB generic
    };

    explicit AFXDPSocket(Config cfg);
    ~AFXDPSocket();

    // Initialize UMEM memory pool, Fill Ring, RX Ring, and socket binding
    bool init();

    // Polls the RX ring buffer for incoming packets. Returns number of packets processed.
    // Zero heap allocations in the hot path.
    template <typename Callback>
    int poll_rx_burst(Callback&& cb, int max_batch = 64);

    int poll_rx(const std::function<void(const RawPacketDesc&)>& cb, int max_batch = 64);

    bool is_running() const { return running_; }
    void stop() { running_ = false; }
    const std::string& get_mode() const { return active_mode_; }

private:
    Config config_;
    bool running_ = false;
    std::string active_mode_ = "SKB_GENERIC";

    // Opaque internals (XSK UMEM, sockets, rings)
    struct Impl;
    std::unique_ptr<Impl> pimpl_;
};
