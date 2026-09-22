// eBPF XDP Kernel Filter for Ultra-Low-Latency Ingress
// Intercepts multicast/unicast UDP packets on ports 5000-5005
// and redirects them directly to user-space AF_XDP socket map (xsks_map).

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/in.h>
#include <linux/udp.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

#define MAX_SOCKS 64

// XSK BPF map: stores file descriptors of AF_XDP sockets indexed by queue ID
struct {
    __uint(type, BPF_MAP_TYPE_XSKMAP);
    __uint(max_entries, MAX_SOCKS);
    __type(key, __u32);
    __type(value, __u32);
} xsks_map SEC(".maps");

SEC("xdp")
int xdp_arbitrage_filter(struct xdp_md *ctx) {
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;

    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    if (eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS;

    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return XDP_PASS;

    if (ip->protocol != IPPROTO_UDP)
        return XDP_PASS;

    struct udphdr *udp = (void *)((__u8 *)ip + (ip->ihl * 4));
    if ((void *)(udp + 1) > data_end)
        return XDP_PASS;

    __u16 dport = bpf_ntohs(udp->dest);

    // Gateways broadcast on dedicated exchange ports 5000-5005
    if (dport >= 5000 && dport <= 5005) {
        __u32 qid = ctx->rx_queue_index;
        // Redirect directly to AF_XDP user-space socket bypass ring
        return bpf_redirect_map(&xsks_map, qid, 0);
    }

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
