// kdb/schema.q

// Define the in-memory tables for normalized ticks
// Time is stored as nanosecond timestamp
SpotBook: ([] time:`timestamp$(); sym:`symbol$(); price:`float$(); size:`int$(); side:`char$(); exch:`symbol$())

OptBook: ([] time:`timestamp$(); sym:`symbol$(); price:`float$(); size:`int$(); side:`char$(); exch:`symbol$())
