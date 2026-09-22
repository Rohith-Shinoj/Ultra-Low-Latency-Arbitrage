#pragma once
#include <cstdint>
#include <cstring>
#include <array>
#include <string_view>
#include <limits>

namespace ull {

enum VenueId : uint8_t {
    // 3 Equity Options Venues
    VENUE_CBOE_OPT    = 0,
    VENUE_NASDAQ_OPT  = 1,
    VENUE_OPRA_OPT    = 2,
    // 3 Crypto Options Venues
    VENUE_DERIBIT_OPT = 3,
    VENUE_OKX_OPT     = 4,
    VENUE_BINANCE_OPT = 5,
    NUM_VENUES        = 6
};

inline const char* venue_to_string(uint8_t id) noexcept {
    switch (id) {
        case VENUE_CBOE_OPT:    return "CBOE_OPTIONS";
        case VENUE_NASDAQ_OPT:  return "NASDAQ_OPTIONS";
        case VENUE_OPRA_OPT:    return "OPRA_COMPOSITE";
        case VENUE_DERIBIT_OPT: return "DERIBIT_OPTIONS";
        case VENUE_OKX_OPT:     return "OKX_OPTIONS";
        case VENUE_BINANCE_OPT: return "BINANCE_OPTIONS";
        default:                return "UNKNOWN";
    }
}

// 64-byte cache-line aligned price level to avoid false sharing
struct alignas(64) PriceLevel {
    double price{0.0};
    int32_t quantity{0};
    uint64_t update_time{0}; // nanoseconds
    uint8_t reserved[44];    // Pad to exactly 64 bytes
};

// Single venue L2 Order Book state
struct alignas(64) VenueBook {
    PriceLevel best_bid;
    PriceLevel best_ask;
    double last_trade_price{0.0};
    int32_t last_trade_size{0};
    uint64_t last_update_time{0};
    uint32_t update_count{0};
    char symbol[16]{0};
};

class alignas(64) MultiVenueOrderBook {
public:
    MultiVenueOrderBook() {
        for (size_t i = 0; i < NUM_VENUES; ++i) {
            books_[i].best_bid.price = 0.0;
            books_[i].best_bid.quantity = 0;
            books_[i].best_ask.price = std::numeric_limits<double>::infinity();
            books_[i].best_ask.quantity = 0;
        }
        std::strncpy(books_[VENUE_CBOE_OPT].symbol, "SPY_C610", 15);
        std::strncpy(books_[VENUE_NASDAQ_OPT].symbol, "SPY_C610", 15);
        std::strncpy(books_[VENUE_OPRA_OPT].symbol, "SPY_C610", 15);
        std::strncpy(books_[VENUE_DERIBIT_OPT].symbol, "BTC_C80K", 15);
        std::strncpy(books_[VENUE_OKX_OPT].symbol, "BTC_C80K", 15);
        std::strncpy(books_[VENUE_BINANCE_OPT].symbol, "BTC_C80K", 15);
    }

    inline void update_bid(uint8_t venue_id, double price, int32_t qty, uint64_t ts) noexcept {
        if (__builtin_expect(venue_id < NUM_VENUES, 1)) {
            auto& b = books_[venue_id];
            b.best_bid.price = price;
            b.best_bid.quantity = qty;
            b.best_bid.update_time = ts;
            b.last_update_time = ts;
            b.update_count++;
        }
    }

    inline void update_ask(uint8_t venue_id, double price, int32_t qty, uint64_t ts) noexcept {
        if (__builtin_expect(venue_id < NUM_VENUES, 1)) {
            auto& b = books_[venue_id];
            b.best_ask.price = price;
            b.best_ask.quantity = qty;
            b.best_ask.update_time = ts;
            b.last_update_time = ts;
            b.update_count++;
        }
    }

    inline void update_trade(uint8_t venue_id, double price, int32_t qty, uint64_t ts) noexcept {
        if (__builtin_expect(venue_id < NUM_VENUES, 1)) {
            auto& b = books_[venue_id];
            b.last_trade_price = price;
            b.last_trade_size = qty;
            b.last_update_time = ts;
            b.update_count++;
        }
    }

    inline void update_bbo(uint8_t venue_id, double bid_px, int32_t bid_qty,
                           double ask_px, int32_t ask_qty, uint64_t ts) noexcept {
        if (__builtin_expect(venue_id < NUM_VENUES, 1)) {
            auto& b = books_[venue_id];
            b.best_bid.price = bid_px;
            b.best_bid.quantity = bid_qty;
            b.best_bid.update_time = ts;
            b.best_ask.price = ask_px;
            b.best_ask.quantity = ask_qty;
            b.best_ask.update_time = ts;
            b.last_update_time = ts;
            b.update_count++;
        }
    }

    [[nodiscard]] inline const VenueBook& get_book(uint8_t venue_id) const noexcept {
        return books_[venue_id];
    }

    [[nodiscard]] inline bool has_bbo(uint8_t venue_id) const noexcept {
        return books_[venue_id].best_bid.price > 0.0 && 
               books_[venue_id].best_ask.price < std::numeric_limits<double>::infinity();
    }

private:
    std::array<VenueBook, NUM_VENUES> books_;
};

} // namespace ull
