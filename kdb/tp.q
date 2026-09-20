// kdb/tp.q
// Start with port 5010 (e.g. q kdb/tp.q -p 5010)

\l kdb/schema.q

// The IPC insert handler for qPython (handles type casting)
upd: { [t;x] 
    t_sym: $[10h=type t; `$t; t];
    row: (`timestamp$x[0]; `$x[1]; `float$x[2]; `int$x[3]; first x[4]; `$x[5]);
    t_sym insert row
 }

// Periodic disk flush
.z.ts: { 
    if[count SpotBook; `:hdb/SpotBook/ upsert SpotBook];
    if[count OptBook; `:hdb/OptBook/ upsert OptBook];
 }

// Start timer
\t 10000

show "Tickerplant started on port ", string system "p"
