#pragma once
#include <cstdint>

#pragma pack(push, 1)

// Common ITCH 5.0 Header
struct ITCH50MessageHeader {
    char message_type;
};

// ITCH 5.0 Add Order Message
struct ITCH50AddOrder {
    char message_type; // 'A'
    uint16_t stock_locate;
    uint16_t tracking_number;
    uint64_t timestamp; // Nanoseconds since midnight
    uint64_t order_reference_number;
    char buy_sell_indicator; // 'B' or 'S'
    uint32_t shares;
    char stock[8]; // Symbol, padded with spaces
    uint32_t price; // Decimal price with 4 implied decimals
};

// ITCH 5.0 Order Executed Message
struct ITCH50OrderExecuted {
    char message_type; // 'E'
    uint16_t stock_locate;
    uint16_t tracking_number;
    uint64_t timestamp;
    uint64_t order_reference_number;
    uint32_t executed_shares;
    uint64_t match_number;
};

#pragma pack(pop)
