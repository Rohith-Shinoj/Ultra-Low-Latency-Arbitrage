#pragma once
#include <cstdint>
#include <vector>
#include <algorithm>
#include <numeric>
#include <chrono>
#include <iostream>
#include <iomanip>
#include <cmath>

#if defined(__x86_64__)
#include <x86intrin.h>
#endif

namespace ull {

class BenchmarkTimer {
public:
    static inline uint64_t rdtsc() noexcept {
#if defined(__aarch64__)
        uint64_t val;
        asm volatile("mrs %0, cntvct_el0" : "=r"(val));
        return val;
#elif defined(__x86_64__)
        return __rdtsc();
#else
        return static_cast<uint64_t>(std::chrono::steady_clock::now().time_since_epoch().count());
#endif
    }

    static inline uint64_t frequency() noexcept {
#if defined(__aarch64__)
        uint64_t freq;
        asm volatile("mrs %0, cntfrq_el0" : "=r"(freq));
        return freq;
#elif defined(__x86_64__)
        // 2.5 GHz nominal clock on modern x86 server
        return 2500000000ULL;
#else
        return 1000000000ULL;
#endif
    }

    static inline uint64_t cycles_to_ns(uint64_t cycles, uint64_t freq) noexcept {
        return (cycles * 1000000000ULL) / freq;
    }
};

struct LatencyRecord {
    uint64_t t_ingress_cycles;
    uint64_t t_parse_cycles;
    uint64_t t_book_cycles;
    uint64_t t_arb_cycles;
    uint64_t t_total_cycles;
};

class LatencyTracker {
public:
    static constexpr size_t MAX_SAMPLES = 100000;

    LatencyTracker() : freq_(BenchmarkTimer::frequency()) {
        samples_.reserve(MAX_SAMPLES);
    }

    inline void record(uint64_t ingress_cycles, uint64_t parse_cycles, uint64_t book_cycles, uint64_t arb_cycles) noexcept {
        uint64_t total = ingress_cycles + parse_cycles + book_cycles + arb_cycles;
        if (samples_.size() < MAX_SAMPLES) {
            samples_.push_back({ingress_cycles, parse_cycles, book_cycles, arb_cycles, total});
        }
    }

    struct LatencyStats {
        size_t count;
        double min_ns;
        double p50_ns;
        double p90_ns;
        double p99_ns;
        double p999_ns;
        double max_ns;
        double mean_ns;
    };

    LatencyStats compute_stats(const std::vector<uint64_t>& cycles) const {
        if (cycles.empty()) {
            return {0, 0, 0, 0, 0, 0, 0, 0};
        }
        std::vector<double> ns_values;
        ns_values.reserve(cycles.size());
        for (uint64_t c : cycles) {
            ns_values.push_back(static_cast<double>(BenchmarkTimer::cycles_to_ns(c, freq_)));
        }
        std::sort(ns_values.begin(), ns_values.end());

        size_t n = ns_values.size();
        double sum = std::accumulate(ns_values.begin(), ns_values.end(), 0.0);

        LatencyStats s;
        s.count = n;
        s.min_ns = ns_values.front();
        s.p50_ns = ns_values[static_cast<size_t>(n * 0.50)];
        s.p90_ns = ns_values[static_cast<size_t>(n * 0.90)];
        s.p99_ns = ns_values[static_cast<size_t>(n * 0.99)];
        s.p999_ns = ns_values[std::min(static_cast<size_t>(n * 0.999), n - 1)];
        s.max_ns = ns_values.back();
        s.mean_ns = sum / n;
        return s;
    }

    void print_report(std::ostream& os = std::cout) const {
        if (samples_.empty()) {
            os << "No latency samples recorded yet.\n";
            return;
        }

        std::vector<uint64_t> ingress_c, parse_c, book_c, arb_c, total_c;
        ingress_c.reserve(samples_.size());
        parse_c.reserve(samples_.size());
        book_c.reserve(samples_.size());
        arb_c.reserve(samples_.size());
        total_c.reserve(samples_.size());

        for (const auto& s : samples_) {
            ingress_c.push_back(s.t_ingress_cycles);
            parse_c.push_back(s.t_parse_cycles);
            book_c.push_back(s.t_book_cycles);
            arb_c.push_back(s.t_arb_cycles);
            total_c.push_back(s.t_total_cycles);
        }

        auto st_ingress = compute_stats(ingress_c);
        auto st_parse   = compute_stats(parse_c);
        auto st_book    = compute_stats(book_c);
        auto st_arb     = compute_stats(arb_c);
        auto st_total   = compute_stats(total_c);

        os << "\n═══════════════════════════════════════════════════════════════════════════════════════════════════════════════\n";
        os << "                       ULTRA-LOW-LATENCY PIPELINE BENCHMARK REPORT (GENUINE HARDWARE CYCLES)                   \n";
        os << "═══════════════════════════════════════════════════════════════════════════════════════════════════════════════\n";
        os << " Hardware Timer Freq: " << (freq_ / 1000000.0) << " MHz | Total Processed Samples: " << samples_.size() << "\n";
        os << "───────────────────────────────────────────────────────────────────────────────────────────────────────────────\n";
        os << std::left << std::setw(20) << "Stage"
           << std::right << std::setw(12) << "Min (ns)"
           << std::setw(12) << "P50 (ns)"
           << std::setw(12) << "P90 (ns)"
           << std::setw(12) << "P99 (ns)"
           << std::setw(14) << "P99.9 (ns)"
           << std::setw(12) << "Max (ns)"
           << std::setw(12) << "Mean (ns)" << "\n";
        os << "───────────────────────────────────────────────────────────────────────────────────────────────────────────────\n";

        auto print_row = [&](const std::string& name, const LatencyStats& s) {
            os << std::left << std::setw(20) << name
               << std::right << std::fixed << std::setprecision(1)
               << std::setw(12) << s.min_ns
               << std::setw(12) << s.p50_ns
               << std::setw(12) << s.p90_ns
               << std::setw(12) << s.p99_ns
               << std::setw(14) << s.p999_ns
               << std::setw(12) << s.max_ns
               << std::setw(12) << s.mean_ns << "\n";
        };

        print_row("1. Packet Ingress", st_ingress);
        print_row("2. Zero-Copy Parse", st_parse);
        print_row("3. L2 Book Update", st_book);
        print_row("4. Arb Strategy", st_arb);
        os << "───────────────────────────────────────────────────────────────────────────────────────────────────────────────\n";
        print_row("END-TO-END (T2T)", st_total);
        os << "═══════════════════════════════════════════════════════════════════════════════════════════════════════════════\n\n";
    }

    const std::vector<LatencyRecord>& get_samples() const noexcept { return samples_; }
    void clear() noexcept { samples_.clear(); }

private:
    uint64_t freq_;
    std::vector<LatencyRecord> samples_;
};

} // namespace ull
