#pragma once
#include <cstdint>

#pragma pack(push, 1)

// SBE Standard Message Header (MDP 3.0)
struct SBEHeader {
    uint16_t block_length;
    uint16_t template_id;
    uint16_t schema_id;
    uint16_t version;
};

// Simplified MDIncrementalRefreshBook (Options Order Book Update)
struct CMEBookUpdate {
    SBEHeader header; 
    uint64_t transact_time; // Nanoseconds
    uint32_t match_event_indicator;
    
    // Group: NoMDEntries
    uint8_t num_md_entries;
    
    // In actual SBE, this is a variable repeating group. 
    // We hardcode a single entry for this prototype's fixed-size multicast.
    struct MDEntry {
        uint8_t md_update_action; // 0=New, 1=Change, 2=Delete
        char md_entry_type; // '0'=Bid, '1'=Offer
        uint32_t security_id; // Unique option ID (e.g., Strike/Expiry encoding)
        uint32_t rpt_seq; 
        int64_t md_entry_px; // Price
        int32_t md_entry_size; // Quantity
    } entry;
};

#pragma pack(pop)
