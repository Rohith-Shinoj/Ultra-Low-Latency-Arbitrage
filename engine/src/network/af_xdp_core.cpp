#include "af_xdp_core.h"
#include <iostream>
#include <cstring>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <linux/if_link.h>
#include <sys/mman.h>
#include <netinet/in.h>
#include <sys/epoll.h>
#include <net/if.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/udp.h>
#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <xdp/xsk.h>

struct AFXDPSocket::Impl {
    struct xsk_umem_info {
        struct xsk_ring_prod fq;
        struct xsk_ring_cons cq;
        struct xsk_umem *umem = nullptr;
        void *buffer = nullptr;
    } umem_info;

    struct xsk_socket_info {
        struct xsk_ring_cons rx;
        struct xsk_ring_prod tx;
        struct xsk_socket *xsk = nullptr;
    } xsk_info;

    struct bpf_object *bpf_obj = nullptr;
    int ifindex = -1;
    bool prog_attached = false;

    // Fast epoll / socket fallback array for ports 5000-5005
    int epoll_fd = -1;
    int udp_socks[6] = {-1, -1, -1, -1, -1, -1};
    uint16_t ports[6] = {5000, 5001, 5002, 5003, 5004, 5005};
    uint8_t rx_buffer[65536];
    bool use_xsk = false;
};

AFXDPSocket::AFXDPSocket(Config cfg)
    : config_(std::move(cfg)), pimpl_(std::make_unique<Impl>()) {
}

AFXDPSocket::~AFXDPSocket() {
    stop();
}

void AFXDPSocket::stop() {
    if (running_) {
        running_ = false;
        if (pimpl_) {
            if (pimpl_->prog_attached && pimpl_->ifindex > 0) {
                bpf_xdp_detach(pimpl_->ifindex, XDP_FLAGS_SKB_MODE, NULL);
                pimpl_->prog_attached = false;
            }
            if (pimpl_->bpf_obj) {
                bpf_object__close(pimpl_->bpf_obj);
                pimpl_->bpf_obj = nullptr;
            }
            if (pimpl_->use_xsk) {
                if (pimpl_->xsk_info.xsk) {
                    xsk_socket__delete(pimpl_->xsk_info.xsk);
                    pimpl_->xsk_info.xsk = nullptr;
                }
                if (pimpl_->umem_info.umem) {
                    xsk_umem__delete(pimpl_->umem_info.umem);
                    pimpl_->umem_info.umem = nullptr;
                }
                if (pimpl_->umem_info.buffer) {
                    free(pimpl_->umem_info.buffer);
                    pimpl_->umem_info.buffer = nullptr;
                }
                pimpl_->use_xsk = false;
            }
            if (pimpl_->epoll_fd >= 0) {
                close(pimpl_->epoll_fd);
                pimpl_->epoll_fd = -1;
            }
            for (int &fd : pimpl_->udp_socks) {
                if (fd >= 0) {
                    close(fd);
                    fd = -1;
                }
            }
        }
    }
}

bool AFXDPSocket::init() {
    // 0. Hardware Scan: Probe for Solarflare OpenOnload and SFC PCIe adapters
    solarflare_scan_ = ull::SolarflareManager::scan_hardware();

    pimpl_->ifindex = if_nametoindex(config_.ifname.c_str());
    if (pimpl_->ifindex == 0) {
        std::cerr << "[AF_XDP Error] Invalid interface name: " << config_.ifname << std::endl;
        return false;
    }

    // 1. Locate and load custom eBPF XDP filter (xdp_prog.o)
    const char *prog_candidates[] = {
        "engine/bin/xdp_prog.o",
        "bin/xdp_prog.o",
        "/home/ubuntu/ultra-low-latency-arbitrage/engine/bin/xdp_prog.o"
    };
    const char *bpf_file = nullptr;
    for (const char *path : prog_candidates) {
        if (access(path, R_OK) == 0) {
            bpf_file = path;
            break;
        }
    }

    if (bpf_file) {
        pimpl_->bpf_obj = bpf_object__open_file(bpf_file, NULL);
        if (!pimpl_->bpf_obj) {
            std::cerr << "[AF_XDP Error] Failed to open eBPF file " << bpf_file 
                      << ": " << strerror(errno) << std::endl;
        } else {
            int err = bpf_object__load(pimpl_->bpf_obj);
            if (err) {
                std::cerr << "[AF_XDP Error] Failed to load eBPF object: " 
                          << strerror(-err) << std::endl;
                bpf_object__close(pimpl_->bpf_obj);
                pimpl_->bpf_obj = nullptr;
            } else {
                struct bpf_program *prog = bpf_object__find_program_by_name(pimpl_->bpf_obj, "xdp_arbitrage_filter");
                if (!prog) {
                    std::cerr << "[AF_XDP Error] Program 'xdp_arbitrage_filter' not found in object\n";
                    bpf_object__close(pimpl_->bpf_obj);
                    pimpl_->bpf_obj = nullptr;
                } else {
                    int prog_fd = bpf_program__fd(prog);
                    // Detach any previous program on interface
                    bpf_xdp_detach(pimpl_->ifindex, XDP_FLAGS_SKB_MODE, NULL);
                    int ret = bpf_xdp_attach(pimpl_->ifindex, prog_fd, XDP_FLAGS_SKB_MODE, NULL);
                    if (ret < 0) {
                        std::cerr << "[AF_XDP Error] bpf_xdp_attach failed on '" << config_.ifname
                                  << "' (code " << ret << "): " << strerror(-ret) << "\n";
                        bpf_object__close(pimpl_->bpf_obj);
                        pimpl_->bpf_obj = nullptr;
                    } else {
                        pimpl_->prog_attached = true;
                        std::cout << "[AF_XDP] Successfully loaded & attached eBPF filter (" << bpf_file 
                                  << ") to '" << config_.ifname << "' (ports 5000-5005 redirected to XSK)\n";
                    }
                }
            }
        }
    } else {
        std::cerr << "[AF_XDP Warning] xdp_prog.o not found. Ensure engine was built via make.\n";
    }

    // 2. Configure UMEM and genuine AF_XDP socket
    size_t umem_size = config_.num_frames * config_.frame_size;
    void *bufs = nullptr;

    if (pimpl_->prog_attached && posix_memalign(&bufs, getpagesize(), umem_size) == 0) {
        pimpl_->umem_info.buffer = bufs;

        struct xsk_umem_config ucfg = {};
        ucfg.fill_size = config_.num_frames;
        ucfg.comp_size = config_.num_frames;
        ucfg.frame_size = config_.frame_size;
        ucfg.frame_headroom = XSK_UMEM__DEFAULT_FRAME_HEADROOM;
        ucfg.flags = 0;

        int ret = xsk_umem__create(&pimpl_->umem_info.umem, bufs, umem_size,
                                   &pimpl_->umem_info.fq, &pimpl_->umem_info.cq, &ucfg);
        if (ret == 0) {
            struct xsk_socket_config xcfg = {};
            xcfg.rx_size = config_.num_frames / 2;
            xcfg.tx_size = config_.num_frames / 2;
            xcfg.libbpf_flags = XSK_LIBBPF_FLAGS__INHIBIT_PROG_LOAD;
            xcfg.xdp_flags = config_.zero_copy ? XDP_FLAGS_DRV_MODE : XDP_FLAGS_SKB_MODE;
            xcfg.bind_flags = XDP_USE_NEED_WAKEUP;

            ret = xsk_socket__create(&pimpl_->xsk_info.xsk, config_.ifname.c_str(),
                                     config_.queue_id, pimpl_->umem_info.umem,
                                     &pimpl_->xsk_info.rx, &pimpl_->xsk_info.tx, &xcfg);
            if (ret == 0) {
                // Register AF_XDP socket in eBPF xsks_map
                struct bpf_map *map = bpf_object__find_map_by_name(pimpl_->bpf_obj, "xsks_map");
                if (map) {
                    int map_fd = bpf_map__fd(map);
                    int xsk_fd = xsk_socket__fd(pimpl_->xsk_info.xsk);
                    uint32_t qid = config_.queue_id;
                    int mret = bpf_map_update_elem(map_fd, &qid, &xsk_fd, BPF_ANY);
                    if (mret != 0) {
                        std::cerr << "[AF_XDP Error] Failed to update xsks_map: " << strerror(errno) << "\n";
                    } else {
                        std::cout << "[AF_XDP] Registered AF_XDP socket (fd=" << xsk_fd 
                                  << ") in eBPF xsks_map[queue=" << qid << "]\n";
                    }
                } else {
                    std::cerr << "[AF_XDP Error] xsks_map not found in eBPF object!\n";
                }

                // Populate Fill Ring with initial frame addresses
                uint32_t idx = 0;
                if (xsk_ring_prod__reserve(&pimpl_->umem_info.fq, config_.num_frames / 2, &idx) > 0) {
                    for (uint32_t i = 0; i < config_.num_frames / 2; i++) {
                        *xsk_ring_prod__fill_addr(&pimpl_->umem_info.fq, idx++) = i * config_.frame_size;
                    }
                    xsk_ring_prod__submit(&pimpl_->umem_info.fq, config_.num_frames / 2);
                }

                pimpl_->use_xsk = true;
                if (solarflare_scan_.is_accelerated()) {
                    active_mode_ = "Solarflare OpenOnload (Direct HW Kernel Bypass)";
                } else {
                    active_mode_ = config_.zero_copy ? "AF_XDP (Zero-Copy DRV)" : "AF_XDP (Generic SKB Bypass)";
                }
                running_ = true;
                std::cout << "[AF_XDP] Successfully initialized on interface '" 
                          << config_.ifname << "' in mode: " << active_mode_ << std::endl;
                return true;
            } else {
                std::cerr << "[AF_XDP Error] xsk_socket__create failed (code " << ret << "): "
                          << strerror(-ret) << ". Process requires root / CAP_NET_ADMIN / CAP_BPF.\n";
            }
        } else {
            std::cerr << "[AF_XDP Error] xsk_umem__create failed (code " << ret << "): "
                      << strerror(-ret) << "\n";
        }
        free(bufs);
        pimpl_->umem_info.buffer = nullptr;
    }

    if (pimpl_->prog_attached && pimpl_->ifindex > 0) {
        bpf_xdp_detach(pimpl_->ifindex, XDP_FLAGS_SKB_MODE, NULL);
        pimpl_->prog_attached = false;
    }
    if (pimpl_->bpf_obj) {
        bpf_object__close(pimpl_->bpf_obj);
        pimpl_->bpf_obj = nullptr;
    }

    // 3. Fallback path if AF_XDP cannot be acquired (e.g. without sudo/root)
    std::cout << "[Ingress Fallback] Activating standard Linux POSIX epoll UDP sockets for ports 5000-5005." << std::endl;
    pimpl_->epoll_fd = epoll_create1(0);
    if (pimpl_->epoll_fd < 0) return false;

    for (int i = 0; i < 6; i++) {
        int fd = socket(AF_INET, SOCK_DGRAM | SOCK_NONBLOCK, 0);
        if (fd < 0) continue;

        if (solarflare_scan_.is_accelerated()) {
            ull::SolarflareManager::configure_onload_socket(fd);
        }

        int opt = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));

        int rcvbuf = 4 * 1024 * 1024; // 4MB
        setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));

        struct sockaddr_in addr = {};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(pimpl_->ports[i]);

        if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
            struct epoll_event ev = {};
            ev.events = EPOLLIN;
            ev.data.u32 = pimpl_->ports[i];
            epoll_ctl(pimpl_->epoll_fd, EPOLL_CTL_ADD, fd, &ev);
            pimpl_->udp_socks[i] = fd;
        } else {
            close(fd);
            pimpl_->udp_socks[i] = -1;
        }
    }

    pimpl_->use_xsk = false;
    if (solarflare_scan_.is_accelerated()) {
        active_mode_ = "Solarflare OpenOnload (Direct HW Kernel Bypass)";
    } else {
        active_mode_ = "POSIX UDP Epoll (Kernel Fallback - Run with sudo for AF_XDP)";
    }
    running_ = true;
    std::cout << "[Ingress Engine] Listening to Ports 5000-5005 in Mode: " << active_mode_ << std::endl;
    return true;
}

template <typename Callback>
int AFXDPSocket::poll_rx_burst(Callback&& cb, int max_batch) {
    if (!running_) return 0;

    int packets_processed = 0;

    if (pimpl_->use_xsk) {
        // --- AF_XDP Ring Ingress Path ---
        uint32_t idx_rx = 0;
        unsigned int rcvd = xsk_ring_cons__peek(&pimpl_->xsk_info.rx, max_batch, &idx_rx);
        if (rcvd == 0) return 0;

        uint64_t cycles = rdtsc_cycles();
        uint64_t hw_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::high_resolution_clock::now().time_since_epoch()).count();

        uint64_t freed_addrs[64];

        for (unsigned int i = 0; i < rcvd; i++) {
            const struct xdp_desc *desc = xsk_ring_cons__rx_desc(&pimpl_->xsk_info.rx, idx_rx++);
            uint64_t addr = desc->addr;
            uint32_t len = desc->len;
            if (i < 64) freed_addrs[i] = addr;

            const uint8_t *pkt = (const uint8_t *)xsk_umem__get_data(pimpl_->umem_info.buffer, addr);

            // Fast packet header parsing (Eth -> IP -> UDP)
            if (len >= sizeof(struct ethhdr) + sizeof(struct iphdr) + sizeof(struct udphdr)) {
                const struct iphdr *ip = (const struct iphdr *)(pkt + sizeof(struct ethhdr));
                if (ip->protocol == 17) { // UDP
                    const struct udphdr *udp = (const struct udphdr *)((const uint8_t *)ip + (ip->ihl * 4));
                    uint16_t port = ntohs(udp->dest);
                    const uint8_t *payload = (const uint8_t *)(udp + 1);
                    uint32_t payload_len = ntohs(udp->len) - sizeof(struct udphdr);

                    RawPacketDesc raw_desc{payload, payload_len, port, cycles, hw_ns};
                    cb(raw_desc);
                    packets_processed++;
                }
            }
        }
        xsk_ring_cons__release(&pimpl_->xsk_info.rx, rcvd);

        // Replenish Fill Ring with the exact recycled buffer addresses
        uint32_t idx_fq = 0;
        if (xsk_ring_prod__reserve(&pimpl_->umem_info.fq, rcvd, &idx_fq) > 0) {
            for (unsigned int i = 0; i < rcvd; i++) {
                *xsk_ring_prod__fill_addr(&pimpl_->umem_info.fq, idx_fq++) = (i < 64) ? freed_addrs[i] : (i * config_.frame_size);
            }
            xsk_ring_prod__submit(&pimpl_->umem_info.fq, rcvd);
        }
    } else {
        // --- High-Speed Epoll Fallback Path ---
        struct epoll_event events[64];
        int nfds = epoll_wait(pimpl_->epoll_fd, events, max_batch, 0); // Non-blocking poll (0ms)
        if (nfds <= 0) return 0;

        uint64_t cycles = rdtsc_cycles();
        uint64_t hw_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::high_resolution_clock::now().time_since_epoch()).count();

        for (int i = 0; i < nfds; i++) {
            uint16_t port = (uint16_t)events[i].data.u32;
            for (int k = 0; k < 6; k++) {
                if (pimpl_->ports[k] == port && pimpl_->udp_socks[k] >= 0) {
                    ssize_t n = recv(pimpl_->udp_socks[k], pimpl_->rx_buffer, sizeof(pimpl_->rx_buffer), 0);
                    if (n > 0) {
                        RawPacketDesc raw_desc{pimpl_->rx_buffer, (uint32_t)n, port, cycles, hw_ns};
                        cb(raw_desc);
                        packets_processed++;
                    }
                    break;
                }
            }
        }
    }

    return packets_processed;
}

int AFXDPSocket::poll_rx(const std::function<void(const RawPacketDesc&)>& cb, int max_batch) {
    auto fn = cb;
    return poll_rx_burst(std::move(fn), max_batch);
}

// Explicit template instantiation for common callable
template int AFXDPSocket::poll_rx_burst<std::function<void(const RawPacketDesc&)>>(
    std::function<void(const RawPacketDesc&)>&&, int);
