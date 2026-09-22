#pragma once
#include "order_book.h"
#include "benchmark.h"
#include <string>
#include <optional>
#include <cmath>

namespace ull {

enum class StrategyType : uint8_t {
    CROSS_VENUE_CRYPTO_OPT,
    CROSS_VENUE_EQUITY_OPT,
    PUT_CALL_PARITY
};

inline const char* strategy_type_to_string(StrategyType t) noexcept {
    switch (t) {
        case StrategyType::CROSS_VENUE_CRYPTO_OPT: return "CROSS_VENUE_CRYPTO_OPT";
        case StrategyType::CROSS_VENUE_EQUITY_OPT: return "CROSS_VENUE_EQUITY_OPT";
        case StrategyType::PUT_CALL_PARITY:        return "PUT_CALL_PARITY";
        default:                                   return "UNKNOWN";
    }
}

struct alignas(64) ArbSignal {
    uint64_t timestamp_ns{0};
    StrategyType strategy{StrategyType::CROSS_VENUE_CRYPTO_OPT};
    uint8_t buy_venue{0};
    uint8_t sell_venue{0};
    double buy_price{0.0};
    double sell_price{0.0};
    int32_t executable_qty{0};
    double gross_spread{0.0};
    double net_profit_est{0.0};
    uint64_t latency_cycles{0};
};

class ArbitrageStrategy {
public:
    // Crypto taker fees: ~0.04% each side = ~0.08% total hurdle
    static constexpr double CRYPTO_FEE_RATE = 0.0008;
    // Equity options clearing / exchange fee hurdle: ~$0.02 per contract leg
    static constexpr double EQUITY_FEE_PER_LEG = 0.02;

    ArbitrageStrategy() = default;

    // Evaluates cross-venue arbitrage across the 3 crypto options venues:
    // Deribit (VENUE_DERIBIT_OPT), OKX (VENUE_OKX_OPT), Binance (VENUE_BINANCE_OPT)
    [[nodiscard]] std::optional<ArbSignal> evaluate_crypto_arb(
        const MultiVenueOrderBook& book, uint64_t now_ns, uint64_t start_cycles) const noexcept 
    {
        constexpr uint8_t crypto_venues[] = {
            VENUE_DERIBIT_OPT, VENUE_OKX_OPT, VENUE_BINANCE_OPT
        };

        double best_bid = 0.0;
        uint8_t best_bid_venue = 0;
        int32_t best_bid_qty = 0;

        double best_ask = std::numeric_limits<double>::infinity();
        uint8_t best_ask_venue = 0;
        int32_t best_ask_qty = 0;

        for (uint8_t v : crypto_venues) {
            const auto& vb = book.get_book(v);
            if (vb.best_bid.price > best_bid && vb.best_bid.quantity > 0) {
                best_bid = vb.best_bid.price;
                best_bid_venue = v;
                best_bid_qty = vb.best_bid.quantity;
            }
            if (vb.best_ask.price < best_ask && vb.best_ask.price > 0.0 && vb.best_ask.quantity > 0) {
                best_ask = vb.best_ask.price;
                best_ask_venue = v;
                best_ask_qty = vb.best_ask.quantity;
            }
        }

        // Cross-venue crossed market: Best Bid on Venue A > Best Ask on Venue B
        if (best_bid_venue != best_ask_venue && best_bid > best_ask && best_ask > 0.0) {
            double spread = best_bid - best_ask;
            double fee_cost = best_ask * CRYPTO_FEE_RATE;
            double net = spread - fee_cost;

            ArbSignal sig;
            sig.timestamp_ns = now_ns;
            sig.strategy = StrategyType::CROSS_VENUE_CRYPTO_OPT;
            sig.buy_venue = best_ask_venue;     // Buy on the cheaper ask venue
            sig.sell_venue = best_bid_venue;    // Sell on the higher bid venue
            sig.buy_price = best_ask;
            sig.sell_price = best_bid;
            sig.executable_qty = std::min(best_bid_qty, best_ask_qty);
            sig.gross_spread = spread;
            sig.net_profit_est = net;
            sig.latency_cycles = BenchmarkTimer::rdtsc() - start_cycles;
            return sig;
        }

        return std::nullopt;
    }

    // Evaluates cross-exchange arbitrage across the 3 equity options venues:
    // CBOE (VENUE_CBOE_OPT), Nasdaq (VENUE_NASDAQ_OPT), OPRA Composite (VENUE_OPRA_OPT)
    [[nodiscard]] std::optional<ArbSignal> evaluate_equity_arb(
        const MultiVenueOrderBook& book, uint64_t now_ns, uint64_t start_cycles) const noexcept 
    {
        constexpr uint8_t equity_venues[] = {
            VENUE_CBOE_OPT, VENUE_NASDAQ_OPT, VENUE_OPRA_OPT
        };

        double best_bid = 0.0;
        uint8_t best_bid_venue = 0;
        int32_t best_bid_qty = 0;

        double best_ask = std::numeric_limits<double>::infinity();
        uint8_t best_ask_venue = 0;
        int32_t best_ask_qty = 0;

        for (uint8_t v : equity_venues) {
            const auto& vb = book.get_book(v);
            if (vb.best_bid.price > best_bid && vb.best_bid.quantity > 0) {
                best_bid = vb.best_bid.price;
                best_bid_venue = v;
                best_bid_qty = vb.best_bid.quantity;
            }
            if (vb.best_ask.price < best_ask && vb.best_ask.price > 0.0 && vb.best_ask.quantity > 0) {
                best_ask = vb.best_ask.price;
                best_ask_venue = v;
                best_ask_qty = vb.best_ask.quantity;
            }
        }

        if (best_bid_venue != best_ask_venue && best_bid > best_ask && best_ask > 0.0) {
            double spread = best_bid - best_ask;
            double fee_cost = 2.0 * EQUITY_FEE_PER_LEG;
            double net = spread - fee_cost;

            ArbSignal sig;
            sig.timestamp_ns = now_ns;
            sig.strategy = StrategyType::CROSS_VENUE_EQUITY_OPT;
            sig.buy_venue = best_ask_venue;     // Buy from lower ask
            sig.sell_venue = best_bid_venue;    // Sell to higher bid
            sig.buy_price = best_ask;
            sig.sell_price = best_bid;
            sig.executable_qty = std::min(best_bid_qty, best_ask_qty);
            sig.gross_spread = spread;
            sig.net_profit_est = net;
            sig.latency_cycles = BenchmarkTimer::rdtsc() - start_cycles;
            return sig;
        }

        return std::nullopt;
    }
};

} // namespace ull
