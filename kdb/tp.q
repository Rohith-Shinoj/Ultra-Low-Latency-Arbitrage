// kdb/tp.q
// Start with port 5010 (e.g. q kdb/tp.q -p 5010)

\l kdb/schema.q

// Cumulative monotonic tick counter
tot_ticks: 0j;

// The IPC insert handler for qPython (handles type casting)
upd: { [t;x] 
    tot_ticks +: 1j;
    t_sym: $[10h=type t; `$t; t];
    row: (`timestamp$x[0]; `$x[1]; `float$x[2]; `int$x[3]; first x[4]; `$x[5]);
    t_sym insert row
 }

// Periodic rolling memory buffer cleanup (keep last 10,000 rows, no disk flushes)
.z.ts: { 
    @[{if[10000 < count SpotBook; SpotBook:: -10000#SpotBook]}; (); ()];
    @[{if[10000 < count OptBook; OptBook:: -10000#OptBook]}; (); ()];
 }

// Start timer (runs every 1000ms)
\t 1000

show "Tickerplant started on port ", string system "p"
