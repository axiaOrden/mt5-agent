# VCZ lifecycle diagnostic — XAUUSDc H4

Git base: `1c5d5bc`. Input: saved `XAUUSDc` H4 candles (`11,536` rows); H4 Parquet SHA256 `99f64474b340be9adea6141cda9e59d348d442ef07287e5f6f3627f3b371a3a2`. No MT5 or Wine access.

## Scope and Pine mechanics

**Observed:** existing native H4 PVSRA results and the existing V1 VCZ engine produce two independent copies of each qualifying source range. Pine's fixed `direction=0` BELOW selector lowers the top when a later low enters, and `direction=1` ABOVE selector raises the bottom when a later high enters. A low at/below bottom or high at/above top fully recovers the respective copy. The qualifying source is the previous candle, and the next candle can update the newly created copies immediately. NORMAL candles update them too. This report uses full-history research replay with no display-array cap.

**Mechanical interpretation:** a surviving fragment exists because later completed bars have not met that copy's terminal Pine condition. This does not establish what orders, participants, or intentions were present there.

**Market hypothesis:** ideas about orders, stops, continuation, or reversal are untested and are not evaluated here.

## H4 descriptive counts

Recovery timing uses disjoint bins: first update bar (source +1), second (source +2), third–fourth, fifth–eighth, later, and remaining at the stored-history end. A recovery on the creation/update bar has `bars_until_recovery=0` in V1.

| Selector | Zones | Fully recovered | Remaining | Median recovery bars after creation | Median remaining fraction | First | Second | Third–fourth | Fifth–eighth | Later | Still remaining |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BELOW (direction=0) | 1067 | 976 | 91 | 2.000 | 0.291 | 340 | 81 | 136 | 139 | 280 | 91 |
| ABOVE (direction=1) | 1067 | 1042 | 25 | 2.000 | 0.296 | 378 | 76 | 156 | 145 | 287 | 25 |

### Source candle direction

| Source direction | Selector | Zones | Fully recovered | Remaining |
|---|---|---:|---:|---:|
| BULLISH | BELOW | 515 | 455 | 60 |
| BULLISH | ABOVE | 515 | 511 | 4 |
| BEARISH | BELOW | 552 | 521 | 31 |
| BEARISH | ABOVE | 552 | 531 | 21 |

### PVSRA classification

| Source class | Selector | Zones | Fully recovered | Remaining | Median recovery bars after creation |
|---|---|---:|---:|---:|---:|
| ABOVE_AVERAGE | BELOW | 835 | 770 | 65 | 2.000 |
| ABOVE_AVERAGE | ABOVE | 835 | 821 | 14 | 2.000 |
| CLIMAX | BELOW | 232 | 206 | 26 | 3.000 |
| CLIMAX | ABOVE | 232 | 221 | 11 | 5.000 |

## Eleven H4 lifecycle examples

Selection used chronological source-pair scans, never forward return or profit. Upward/downward travel means that within the next four H4 bars, a high exceeded source high + source height or a low fell below source low − source height; the listed cases are the first such sources from April 2024 onward. The dual-immediate case is the first post-April-2024 source whose two copies recovered on bar +1. The interaction case is the first such source whose next qualifying PVSRA bar changes an older copy. The sideways case is the first post-April-2024 source with the next bar strictly inside its high–low range and both copies lasting at least four update bars. The remaining cases are the two oldest survivors, first two sub-10% residuals, first surviving ABOVE copy, and first sub-10% ABOVE residual. Source timestamps are fixed in the diagnostic script for reproducibility.

| Source UTC | Class / source direction | Original height | BELOW outcome | ABOVE outcome | First fully recovered |
|---|---|---:|---|---|---|
| 2024-04-10 20:00 | ABOVE_AVERAGE / BULLISH | 7.693 | recovered after 2 creation bars | recovered after 0 creation bars | ABOVE |
| 2024-04-11 12:00 | ABOVE_AVERAGE / BULLISH | 15.827 | recovered after 12 creation bars | recovered after 0 creation bars | ABOVE |
| 2024-04-12 00:00 | ABOVE_AVERAGE / BULLISH | 20.878 | recovered after 3 creation bars | recovered after 0 creation bars | ABOVE |
| 2024-04-12 08:00 | ABOVE_AVERAGE / BEARISH | 10.224 | recovered after 0 creation bars | recovered after 0 creation bars | both together |
| 2024-04-12 16:00 | CLIMAX / BEARISH | 61.734 | recovered after 5 creation bars | recovered after 12 creation bars | BELOW |
| 2024-05-03 12:00 | CLIMAX / BEARISH | 43.623 | remaining fraction 0.221 | recovered after 4 creation bars | ABOVE |
| 2024-06-26 12:00 | ABOVE_AVERAGE / BEARISH | 24.245 | remaining fraction 0.118 | recovered after 4 creation bars | ABOVE |
| 2024-08-22 12:00 | CLIMAX / BEARISH | 33.377 | remaining fraction 0.031 | recovered after 5 creation bars | ABOVE |
| 2024-09-06 16:00 | ABOVE_AVERAGE / BEARISH | 20.818 | remaining fraction 0.021 | recovered after 6 creation bars | ABOVE |
| 2026-01-29 04:00 | ABOVE_AVERAGE / BULLISH | 79.241 | recovered after 0 creation bars | remaining fraction 0.510 | BELOW |
| 2026-01-30 00:00 | CLIMAX / BEARISH | 338.900 | recovered after 1 creation bars | remaining fraction 0.094 | BELOW |

### 1. 2024-04-10 20:00 UTC — upward travel; both copies recovered within three update bars

SOURCE XAUUSDc H4: open `2024-04-10 20:00 UTC`, close/knowledge `2024-04-11 00:00 UTC`; ABOVE_AVERAGE, candle BULLISH, flag `+2`. OHLC `2329.692/2337.204/2329.511/2335.487`; original VCZ `[2329.511, 2337.204]`. BELOW direction=0 ID `e954366cf0b405ab9eb92b24`; ABOVE direction=1 ID `5bcdfad68ca0e43c85360df4`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-04-11 00:00 | 2335.489/2346.915/2333.321/2343.966 | [2329.511, 2337.204] → [2329.511, 2333.321]; shrink: low 2333.321 inside → top 2333.321 | [2329.511, 2337.204] → [2329.511, 2337.204]; fully recovered: close 2343.966 ≥ top |
| +2 | 2024-04-11 04:00 | 2343.911/2346.082/2333.871/2336.396 | [2329.511, 2333.321] → [2329.511, 2333.321]; unchanged | [2329.511, 2337.204] → [2329.511, 2337.204]; already fully recovered |
| +3 | 2024-04-11 08:00 | 2336.439/2339.678/2325.627/2337.251 | [2329.511, 2333.321] → [2329.511, 2333.321]; fully recovered: low 2325.627 ≤ bottom | [2329.511, 2337.204] → [2329.511, 2337.204]; already fully recovered |

FINAL at stored-history end: BELOW FULLY_RECOVERED [2329.511, 2333.321] (updates=1, recovery=2); ABOVE FULLY_RECOVERED [2329.511, 2337.204] (updates=0, recovery=0).

### 2. 2024-04-11 12:00 UTC — new PVSRA while an older BELOW copy is shrinking

SOURCE XAUUSDc H4: open `2024-04-11 12:00 UTC`, close/knowledge `2024-04-11 16:00 UTC`; ABOVE_AVERAGE, candle BULLISH, flag `+2`. OHLC `2337.269/2347.431/2331.604/2344.667`; original VCZ `[2331.604, 2347.431]`. BELOW direction=0 ID `f53c5114e42aa7aeca4f31ef`; ABOVE direction=1 ID `05c828356c330488a5f5b107`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-04-11 16:00 **new PVSRA source** | 2344.713/2374.624/2342.660/2372.744 | [2331.604, 2347.431] → [2331.604, 2342.660]; shrink: low 2342.660 inside → top 2342.660 | [2331.604, 2347.431] → [2331.604, 2347.431]; fully recovered: close 2372.744 ≥ top |
| +2 | 2024-04-11 20:00 **new PVSRA source** | 2372.820/2379.373/2371.219/2376.787 | [2331.604, 2342.660] → [2331.604, 2342.660]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +3 | 2024-04-12 00:00 **new PVSRA source** | 2376.787/2395.458/2374.580/2384.240 | [2331.604, 2342.660] → [2331.604, 2342.660]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +4 | 2024-04-12 04:00 **new PVSRA source** | 2384.247/2400.348/2382.701/2399.913 | [2331.604, 2342.660] → [2331.604, 2342.660]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +5 | 2024-04-12 08:00 **new PVSRA source** | 2399.954/2400.640/2390.416/2395.362 | [2331.604, 2342.660] → [2331.604, 2342.660]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +6 | 2024-04-12 12:00 **new PVSRA source** | 2395.365/2431.527/2382.143/2395.556 | [2331.604, 2342.660] → [2331.604, 2342.660]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +7 | 2024-04-12 16:00 **new PVSRA source** | 2395.517/2395.517/2333.783/2343.375 | [2331.604, 2342.660] → [2331.604, 2333.783]; shrink: low 2333.783 inside → top 2333.783 | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +8 | 2024-04-12 20:00 | 2343.412/2345.169/2341.691/2343.968 | [2331.604, 2333.783] → [2331.604, 2333.783]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +9 | 2024-04-14 20:00 | 2369.105/2371.920/2346.783/2364.486 | [2331.604, 2333.783] → [2331.604, 2333.783]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| +10 | 2024-04-15 00:00 **new PVSRA source** | 2364.665/2366.003/2348.395/2358.511 | [2331.604, 2333.783] → [2331.604, 2333.783]; unchanged | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |
| … | — | 2 unchanged bar(s) omitted | — | — |
| +13 | 2024-04-15 12:00 **new PVSRA source** | 2357.985/2361.138/2324.114/2351.685 | [2331.604, 2333.783] → [2331.604, 2333.783]; fully recovered: low 2324.114 ≤ bottom | [2331.604, 2347.431] → [2331.604, 2347.431]; already fully recovered |

FINAL at stored-history end: BELOW FULLY_RECOVERED [2331.604, 2333.783] (updates=2, recovery=12); ABOVE FULLY_RECOVERED [2331.604, 2347.431] (updates=0, recovery=0).
The 16:00 bar is itself qualifying PVSRA and shrinks the older BELOW copy. It creates a separate pair from its own range when the 20:00 bar is processed: new BELOW `fce3844173e6eb58c05ef9d5`, new ABOVE `619535273df2e356f8acac49`. No zones are merged.

### 3. 2024-04-12 00:00 UTC — downward travel after the source

SOURCE XAUUSDc H4: open `2024-04-12 00:00 UTC`, close/knowledge `2024-04-12 04:00 UTC`; ABOVE_AVERAGE, candle BULLISH, flag `+2`. OHLC `2376.787/2395.458/2374.580/2384.240`; original VCZ `[2374.580, 2395.458]`. BELOW direction=0 ID `f9ef40548286223e18fa1252`; ABOVE direction=1 ID `5418f498cfe0265d7fb7c3ad`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-04-12 04:00 **new PVSRA source** | 2384.247/2400.348/2382.701/2399.913 | [2374.580, 2395.458] → [2374.580, 2382.701]; shrink: low 2382.701 inside → top 2382.701 | [2374.580, 2395.458] → [2374.580, 2395.458]; fully recovered: close 2399.913 ≥ top |
| +2 | 2024-04-12 08:00 **new PVSRA source** | 2399.954/2400.640/2390.416/2395.362 | [2374.580, 2382.701] → [2374.580, 2382.701]; unchanged | [2374.580, 2395.458] → [2374.580, 2395.458]; already fully recovered |
| +3 | 2024-04-12 12:00 **new PVSRA source** | 2395.365/2431.527/2382.143/2395.556 | [2374.580, 2382.701] → [2374.580, 2382.143]; shrink: low 2382.143 inside → top 2382.143 | [2374.580, 2395.458] → [2374.580, 2395.458]; already fully recovered |
| +4 | 2024-04-12 16:00 **new PVSRA source** | 2395.517/2395.517/2333.783/2343.375 | [2374.580, 2382.143] → [2374.580, 2382.143]; fully recovered: close 2343.375 ≤ bottom | [2374.580, 2395.458] → [2374.580, 2395.458]; already fully recovered |

FINAL at stored-history end: BELOW FULLY_RECOVERED [2374.580, 2382.143] (updates=2, recovery=3); ABOVE FULLY_RECOVERED [2374.580, 2395.458] (updates=0, recovery=0).

### 4. 2024-04-12 08:00 UTC — both copies recovered on the first update bar

SOURCE XAUUSDc H4: open `2024-04-12 08:00 UTC`, close/knowledge `2024-04-12 12:00 UTC`; ABOVE_AVERAGE, candle BEARISH, flag `-2`. OHLC `2399.954/2400.640/2390.416/2395.362`; original VCZ `[2390.416, 2400.640]`. BELOW direction=0 ID `a9dcfb8e665ce8072848b270`; ABOVE direction=1 ID `e978eba59a71cb923409ed77`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-04-12 12:00 **new PVSRA source** | 2395.365/2431.527/2382.143/2395.556 | [2390.416, 2400.640] → [2390.416, 2400.640]; fully recovered: low 2382.143 ≤ bottom | [2390.416, 2400.640] → [2390.416, 2400.640]; fully recovered: high 2431.527 ≥ top |

FINAL at stored-history end: BELOW FULLY_RECOVERED [2390.416, 2400.640] (updates=0, recovery=0); ABOVE FULLY_RECOVERED [2390.416, 2400.640] (updates=0, recovery=0).

### 5. 2024-04-12 16:00 UTC — sideways overlap; both copies initially shrink

SOURCE XAUUSDc H4: open `2024-04-12 16:00 UTC`, close/knowledge `2024-04-12 20:00 UTC`; CLIMAX, candle BEARISH, flag `-3`. OHLC `2395.517/2395.517/2333.783/2343.375`; original VCZ `[2333.783, 2395.517]`. BELOW direction=0 ID `f78d6ff0ed55c4480abb37fd`; ABOVE direction=1 ID `9b8c0b4d1fb24ad9999a0e35`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-04-12 20:00 | 2343.412/2345.169/2341.691/2343.968 | [2333.783, 2395.517] → [2333.783, 2341.691]; shrink: low 2341.691 inside → top 2341.691 | [2333.783, 2395.517] → [2345.169, 2395.517]; shrink: high 2345.169 inside → bottom 2345.169 |
| +2 | 2024-04-14 20:00 | 2369.105/2371.920/2346.783/2364.486 | [2333.783, 2341.691] → [2333.783, 2341.691]; unchanged | [2345.169, 2395.517] → [2371.920, 2395.517]; shrink: high 2371.920 inside → bottom 2371.920 |
| +3 | 2024-04-15 00:00 **new PVSRA source** | 2364.665/2366.003/2348.395/2358.511 | [2333.783, 2341.691] → [2333.783, 2341.691]; unchanged | [2371.920, 2395.517] → [2371.920, 2395.517]; unchanged |
| +4 | 2024-04-15 04:00 **new PVSRA source** | 2358.444/2362.467/2349.952/2353.051 | [2333.783, 2341.691] → [2333.783, 2341.691]; unchanged | [2371.920, 2395.517] → [2371.920, 2395.517]; unchanged |
| +5 | 2024-04-15 08:00 **new PVSRA source** | 2353.038/2361.183/2344.710/2357.947 | [2333.783, 2341.691] → [2333.783, 2341.691]; unchanged | [2371.920, 2395.517] → [2371.920, 2395.517]; unchanged |
| +6 | 2024-04-15 12:00 **new PVSRA source** | 2357.985/2361.138/2324.114/2351.685 | [2333.783, 2341.691] → [2333.783, 2341.691]; fully recovered: low 2324.114 ≤ bottom | [2371.920, 2395.517] → [2371.920, 2395.517]; unchanged |
| +7 | 2024-04-15 16:00 **new PVSRA source** | 2351.706/2387.636/2346.117/2386.315 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2371.920, 2395.517] → [2387.636, 2395.517]; shrink: high 2387.636 inside → bottom 2387.636 |
| +8 | 2024-04-15 20:00 | 2386.369/2392.013/2380.037/2381.833 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2387.636, 2395.517] → [2392.013, 2395.517]; shrink: high 2392.013 inside → bottom 2392.013 |
| +9 | 2024-04-16 00:00 | 2381.896/2389.328/2379.216/2387.870 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2392.013, 2395.517] → [2392.013, 2395.517]; unchanged |
| +10 | 2024-04-16 04:00 | 2387.903/2389.020/2362.964/2365.653 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2392.013, 2395.517] → [2392.013, 2395.517]; unchanged |
| … | — | 1 unchanged bar(s) omitted | — | — |
| +12 | 2024-04-16 12:00 **new PVSRA source** | 2373.956/2393.012/2363.470/2385.980 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2392.013, 2395.517] → [2393.012, 2395.517]; shrink: high 2393.012 inside → bottom 2393.012 |
| +13 | 2024-04-16 16:00 **new PVSRA source** | 2386.046/2398.252/2379.716/2389.641 | [2333.783, 2341.691] → [2333.783, 2341.691]; already fully recovered | [2393.012, 2395.517] → [2393.012, 2395.517]; fully recovered: high 2398.252 ≥ top |

FINAL at stored-history end: BELOW FULLY_RECOVERED [2333.783, 2341.691] (updates=1, recovery=5); ABOVE FULLY_RECOVERED [2393.012, 2395.517] (updates=5, recovery=12).

### 6. 2024-05-03 12:00 UTC — oldest surviving H4 copy

SOURCE XAUUSDc H4: open `2024-05-03 12:00 UTC`, close/knowledge `2024-05-03 16:00 UTC`; CLIMAX, candle BEARISH, flag `-3`. OHLC `2298.281/2320.712/2277.089/2293.728`; original VCZ `[2277.089, 2320.712]`. BELOW direction=0 ID `4f709bc26ce9803b25228ecd`; ABOVE direction=1 ID `978d2e04cc83cc14b6291768`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-05-03 16:00 | 2293.774/2303.090/2292.806/2301.365 | [2277.089, 2320.712] → [2277.089, 2292.806]; shrink: low 2292.806 inside → top 2292.806 | [2277.089, 2320.712] → [2303.090, 2320.712]; shrink: high 2303.090 inside → bottom 2303.090 |
| +2 | 2024-05-03 20:00 | 2301.349/2303.414/2300.629/2301.626 | [2277.089, 2292.806] → [2277.089, 2292.806]; unchanged | [2303.090, 2320.712] → [2303.414, 2320.712]; shrink: high 2303.414 inside → bottom 2303.414 |
| +3 | 2024-05-05 20:00 | 2302.321/2303.288/2293.260/2293.968 | [2277.089, 2292.806] → [2277.089, 2292.806]; unchanged | [2303.414, 2320.712] → [2303.414, 2320.712]; unchanged |
| +4 | 2024-05-06 00:00 | 2293.929/2315.394/2291.769/2309.322 | [2277.089, 2292.806] → [2277.089, 2291.769]; shrink: low 2291.769 inside → top 2291.769 | [2303.414, 2320.712] → [2315.394, 2320.712]; shrink: high 2315.394 inside → bottom 2315.394 |
| +5 | 2024-05-06 04:00 | 2309.367/2324.142/2308.130/2322.646 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; fully recovered: close 2322.646 ≥ top |
| +6 | 2024-05-06 08:00 | 2322.643/2323.082/2315.588/2318.193 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| +7 | 2024-05-06 12:00 **new PVSRA source** | 2318.134/2332.092/2314.546/2324.777 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| +8 | 2024-05-06 16:00 | 2324.731/2327.462/2317.607/2325.030 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| +9 | 2024-05-06 20:00 | 2324.991/2328.821/2322.185/2325.943 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| +10 | 2024-05-07 00:00 | 2325.950/2329.926/2319.603/2324.857 | [2277.089, 2291.769] → [2277.089, 2291.769]; unchanged | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| … | — | 145 unchanged bar(s) omitted | — | — |
| +156 | 2024-06-07 16:00 | 2305.019/2314.486/2287.536/2288.334 | [2277.089, 2291.769] → [2277.089, 2287.536]; shrink: low 2287.536 inside → top 2287.536 | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| +157 | 2024-06-07 20:00 | 2288.290/2294.327/2286.723/2293.798 | [2277.089, 2287.536] → [2277.089, 2286.723]; shrink: low 2286.723 inside → top 2286.723 | [2315.394, 2320.712] → [2315.394, 2320.712]; already fully recovered |
| … | — | 3657 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW REMAINING [2277.089, 2286.723] (updates=4, recovery=None); ABOVE FULLY_RECOVERED [2315.394, 2320.712] (updates=3, recovery=4).
Surviving copy age: 3813 H4 bars since creation; remaining fractions: BELOW 0.221, ABOVE —.

### 7. 2024-06-26 12:00 UTC — second-oldest surviving H4 copy

SOURCE XAUUSDc H4: open `2024-06-26 12:00 UTC`, close/knowledge `2024-06-26 16:00 UTC`; ABOVE_AVERAGE, candle BEARISH, flag `-2`. OHLC `2313.049/2317.804/2293.559/2299.919`; original VCZ `[2293.559, 2317.804]`. BELOW direction=0 ID `827c7ee45fd31e12592e4f71`; ABOVE direction=1 ID `f5267634444498651a6fa6c2`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-06-26 16:00 | 2299.959/2302.981/2296.872/2298.625 | [2293.559, 2317.804] → [2293.559, 2296.872]; shrink: low 2296.872 inside → top 2296.872 | [2293.559, 2317.804] → [2302.981, 2317.804]; shrink: high 2302.981 inside → bottom 2302.981 |
| +2 | 2024-06-26 20:00 | 2298.681/2299.222/2296.764/2298.402 | [2293.559, 2296.872] → [2293.559, 2296.764]; shrink: low 2296.764 inside → top 2296.764 | [2302.981, 2317.804] → [2302.981, 2317.804]; unchanged |
| +3 | 2024-06-27 00:00 | 2298.412/2300.100/2296.806/2298.932 | [2293.559, 2296.764] → [2293.559, 2296.764]; unchanged | [2302.981, 2317.804] → [2302.981, 2317.804]; unchanged |
| +4 | 2024-06-27 04:00 | 2298.935/2303.386/2296.429/2302.260 | [2293.559, 2296.764] → [2293.559, 2296.429]; shrink: low 2296.429 inside → top 2296.429 | [2302.981, 2317.804] → [2303.386, 2317.804]; shrink: high 2303.386 inside → bottom 2303.386 |
| +5 | 2024-06-27 08:00 | 2302.213/2317.891/2301.964/2317.020 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; fully recovered: high 2317.891 ≥ top |
| +6 | 2024-06-27 12:00 **new PVSRA source** | 2316.975/2330.936/2316.028/2327.436 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; already fully recovered |
| +7 | 2024-06-27 16:00 | 2327.401/2328.283/2322.391/2325.951 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; already fully recovered |
| +8 | 2024-06-27 20:00 | 2325.917/2328.523/2325.380/2327.720 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; already fully recovered |
| +9 | 2024-06-28 00:00 | 2327.665/2328.265/2319.010/2321.714 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; already fully recovered |
| +10 | 2024-06-28 04:00 | 2321.788/2328.850/2319.712/2327.144 | [2293.559, 2296.429] → [2293.559, 2296.429]; unchanged | [2303.386, 2317.804] → [2303.386, 2317.804]; already fully recovered |
| … | — | 3568 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW REMAINING [2293.559, 2296.429] (updates=3, recovery=None); ABOVE FULLY_RECOVERED [2303.386, 2317.804] (updates=2, recovery=4).
Surviving copy age: 3577 H4 bars since creation; remaining fractions: BELOW 0.118, ABOVE —.

### 8. 2024-08-22 12:00 UTC — earliest surviving fraction below 0.10

SOURCE XAUUSDc H4: open `2024-08-22 12:00 UTC`, close/knowledge `2024-08-22 16:00 UTC`; CLIMAX, candle BEARISH, flag `-3`. OHLC `2499.502/2504.178/2470.801/2481.794`; original VCZ `[2470.801, 2504.178]`. BELOW direction=0 ID `53f4222ea583dffb02b20226`; ABOVE direction=1 ID `6a2e85870b9c34ba04bc89b4`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-08-22 16:00 | 2481.842/2485.950/2478.491/2482.983 | [2470.801, 2504.178] → [2470.801, 2478.491]; shrink: low 2478.491 inside → top 2478.491 | [2470.801, 2504.178] → [2485.950, 2504.178]; shrink: high 2485.950 inside → bottom 2485.950 |
| +2 | 2024-08-22 20:00 | 2483.021/2487.582/2482.373/2487.564 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2485.950, 2504.178] → [2487.582, 2504.178]; shrink: high 2487.582 inside → bottom 2487.582 |
| +3 | 2024-08-23 00:00 | 2487.574/2493.753/2486.469/2493.170 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2487.582, 2504.178] → [2493.753, 2504.178]; shrink: high 2493.753 inside → bottom 2493.753 |
| +4 | 2024-08-23 04:00 | 2493.153/2495.754/2490.540/2493.384 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2493.753, 2504.178] → [2495.754, 2504.178]; shrink: high 2495.754 inside → bottom 2495.754 |
| +5 | 2024-08-23 08:00 | 2493.338/2502.502/2492.991/2501.571 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2495.754, 2504.178] → [2502.502, 2504.178]; shrink: high 2502.502 inside → bottom 2502.502 |
| +6 | 2024-08-23 12:00 **new PVSRA source** | 2501.557/2518.350/2494.453/2509.845 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2502.502, 2504.178] → [2502.502, 2504.178]; fully recovered: close 2509.845 ≥ top |
| +7 | 2024-08-23 16:00 | 2509.884/2513.242/2501.706/2510.772 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| +8 | 2024-08-23 20:00 | 2510.745/2512.459/2509.532/2512.357 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| +9 | 2024-08-25 20:00 | 2512.067/2516.683/2511.068/2515.917 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| +10 | 2024-08-26 00:00 | 2515.903/2517.001/2509.330/2509.769 | [2470.801, 2478.491] → [2470.801, 2478.491]; unchanged | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| … | — | 39 unchanged bar(s) omitted | — | — |
| +50 | 2024-09-03 12:00 **new PVSRA source** | 2489.690/2502.276/2473.282/2488.353 | [2470.801, 2478.491] → [2470.801, 2473.282]; shrink: low 2473.282 inside → top 2473.282 | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| … | — | 4 unchanged bar(s) omitted | — | — |
| +55 | 2024-09-04 08:00 **new PVSRA source** | 2482.172/2491.252/2471.826/2489.177 | [2470.801, 2473.282] → [2470.801, 2471.826]; shrink: low 2471.826 inside → top 2471.826 | [2502.502, 2504.178] → [2502.502, 2504.178]; already fully recovered |
| … | — | 3269 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW REMAINING [2470.801, 2471.826] (updates=3, recovery=None); ABOVE FULLY_RECOVERED [2502.502, 2504.178] (updates=5, recovery=5).
Surviving copy age: 3323 H4 bars since creation; remaining fractions: BELOW 0.031, ABOVE —.

### 9. 2024-09-06 16:00 UTC — second-earliest surviving fraction below 0.10

SOURCE XAUUSDc H4: open `2024-09-06 16:00 UTC`, close/knowledge `2024-09-06 20:00 UTC`; ABOVE_AVERAGE, candle BEARISH, flag `-2`. OHLC `2505.362/2505.882/2485.064/2495.978`; original VCZ `[2485.064, 2505.882]`. BELOW direction=0 ID `aee86771b2cf05dec9c5511b`; ABOVE direction=1 ID `a0c89563a5439998d01e47db`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2024-09-06 20:00 | 2495.939/2497.827/2494.738/2497.555 | [2485.064, 2505.882] → [2485.064, 2494.738]; shrink: low 2494.738 inside → top 2494.738 | [2485.064, 2505.882] → [2497.827, 2505.882]; shrink: high 2497.827 inside → bottom 2497.827 |
| +2 | 2024-09-08 20:00 | 2497.038/2498.277/2495.507/2496.869 | [2485.064, 2494.738] → [2485.064, 2494.738]; unchanged | [2497.827, 2505.882] → [2498.277, 2505.882]; shrink: high 2498.277 inside → bottom 2498.277 |
| +3 | 2024-09-09 00:00 | 2496.871/2500.540/2494.711/2499.286 | [2485.064, 2494.738] → [2485.064, 2494.711]; shrink: low 2494.711 inside → top 2494.711 | [2498.277, 2505.882] → [2500.540, 2505.882]; shrink: high 2500.540 inside → bottom 2500.540 |
| +4 | 2024-09-09 04:00 | 2499.250/2499.540/2485.503/2494.286 | [2485.064, 2494.711] → [2485.064, 2485.503]; shrink: low 2485.503 inside → top 2485.503 | [2500.540, 2505.882] → [2500.540, 2505.882]; unchanged |
| +5 | 2024-09-09 08:00 | 2494.311/2499.137/2489.940/2497.242 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2500.540, 2505.882] → [2500.540, 2505.882]; unchanged |
| +6 | 2024-09-09 12:00 **new PVSRA source** | 2497.287/2505.292/2493.231/2499.081 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2500.540, 2505.882] → [2505.292, 2505.882]; shrink: high 2505.292 inside → bottom 2505.292 |
| +7 | 2024-09-09 16:00 | 2499.107/2506.577/2499.107/2505.960 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2505.292, 2505.882] → [2505.292, 2505.882]; fully recovered: close 2505.960 ≥ top |
| +8 | 2024-09-09 20:00 | 2505.921/2507.701/2505.221/2506.813 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2505.292, 2505.882] → [2505.292, 2505.882]; already fully recovered |
| +9 | 2024-09-10 00:00 | 2506.815/2507.461/2501.370/2502.532 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2505.292, 2505.882] → [2505.292, 2505.882]; already fully recovered |
| +10 | 2024-09-10 04:00 | 2502.500/2507.773/2500.736/2502.792 | [2485.064, 2485.503] → [2485.064, 2485.503]; unchanged | [2505.292, 2505.882] → [2505.292, 2505.882]; already fully recovered |
| … | — | 3245 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW REMAINING [2485.064, 2485.503] (updates=3, recovery=None); ABOVE FULLY_RECOVERED [2505.292, 2505.882] (updates=4, recovery=6).
Surviving copy age: 3254 H4 bars since creation; remaining fractions: BELOW 0.021, ABOVE —.

### 10. 2026-01-29 04:00 UTC — earliest surviving ABOVE copy

SOURCE XAUUSDc H4: open `2026-01-29 04:00 UTC`, close/knowledge `2026-01-29 08:00 UTC`; ABOVE_AVERAGE, candle BULLISH, flag `+2`. OHLC `5545.731/5595.349/5516.108/5548.968`; original VCZ `[5516.108, 5595.349]`. BELOW direction=0 ID `a4295268cce423457930f245`; ABOVE direction=1 ID `a6e3e490256b48ca7f51763d`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2026-01-29 08:00 | 5548.933/5554.952/5470.739/5522.666 | [5516.108, 5595.349] → [5516.108, 5595.349]; fully recovered: low 5470.739 ≤ bottom | [5516.108, 5595.349] → [5554.952, 5595.349]; shrink: high 5554.952 inside → bottom 5554.952 |
| +2 | 2026-01-29 12:00 **new PVSRA source** | 5522.639/5549.504/5094.978/5182.895 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +3 | 2026-01-29 16:00 **new PVSRA source** | 5182.780/5375.460/5172.031/5305.838 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +4 | 2026-01-29 20:00 | 5305.702/5448.551/5282.791/5438.589 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +5 | 2026-01-30 00:00 **new PVSRA source** | 5438.551/5450.946/5112.046/5196.573 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +6 | 2026-01-30 04:00 **new PVSRA source** | 5196.535/5241.616/5117.625/5181.217 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +7 | 2026-01-30 08:00 **new PVSRA source** | 5181.171/5181.171/4940.267/5136.072 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +8 | 2026-01-30 12:00 **new PVSRA source** | 5136.100/5145.913/4980.398/5050.424 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +9 | 2026-01-30 16:00 **new PVSRA source** | 5050.472/5051.662/4682.526/4932.661 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| +10 | 2026-01-30 20:00 | 4932.701/4932.980/4809.015/4891.496 | [5516.108, 5595.349] → [5516.108, 5595.349]; already fully recovered | [5554.952, 5595.349] → [5554.952, 5595.349]; unchanged |
| … | — | 1022 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW FULLY_RECOVERED [5516.108, 5595.349] (updates=0, recovery=0); ABOVE REMAINING [5554.952, 5595.349] (updates=1, recovery=None).
Surviving copy age: 1031 H4 bars since creation; remaining fractions: BELOW —, ABOVE 0.510.

### 11. 2026-01-30 00:00 UTC — earliest ABOVE residual below 0.10

SOURCE XAUUSDc H4: open `2026-01-30 00:00 UTC`, close/knowledge `2026-01-30 04:00 UTC`; CLIMAX, candle BEARISH, flag `-3`. OHLC `5438.551/5450.946/5112.046/5196.573`; original VCZ `[5112.046, 5450.946]`. BELOW direction=0 ID `52c505293b19bfe8c8929749`; ABOVE direction=1 ID `6cad8e492a13c284decdc274`.

On bar +1 the source first becomes eligible for zone creation; that same completed bar immediately updates both copies.

| Bar | UTC open | OHLC | BELOW before → after; exact condition | ABOVE before → after; exact condition |
|---:|---|---|---|---|
| +1 | 2026-01-30 04:00 **new PVSRA source** | 5196.535/5241.616/5117.625/5181.217 | [5112.046, 5450.946] → [5112.046, 5117.625]; shrink: low 5117.625 inside → top 5117.625 | [5112.046, 5450.946] → [5241.616, 5450.946]; shrink: high 5241.616 inside → bottom 5241.616 |
| +2 | 2026-01-30 08:00 **new PVSRA source** | 5181.171/5181.171/4940.267/5136.072 | [5112.046, 5117.625] → [5112.046, 5117.625]; fully recovered: low 4940.267 ≤ bottom | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +3 | 2026-01-30 12:00 **new PVSRA source** | 5136.100/5145.913/4980.398/5050.424 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +4 | 2026-01-30 16:00 **new PVSRA source** | 5050.472/5051.662/4682.526/4932.661 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +5 | 2026-01-30 20:00 | 4932.701/4932.980/4809.015/4891.496 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +6 | 2026-02-01 20:00 | 4793.519/4819.788/4697.912/4741.422 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +7 | 2026-02-02 00:00 **new PVSRA source** | 4741.564/4884.890/4585.323/4646.594 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +8 | 2026-02-02 04:00 **new PVSRA source** | 4646.496/4713.526/4401.961/4587.176 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +9 | 2026-02-02 08:00 | 4587.205/4779.775/4561.465/4766.028 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| +10 | 2026-02-02 12:00 | 4765.857/4812.462/4617.049/4619.977 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5241.616, 5450.946]; unchanged |
| … | — | 94 unchanged bar(s) omitted | — | — |
| +105 | 2026-02-23 20:00 | 5215.681/5249.589/5214.956/5235.990 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5241.616, 5450.946] → [5249.589, 5450.946]; shrink: high 5249.589 inside → bottom 5249.589 |
| … | — | 22 unchanged bar(s) omitted | — | — |
| +128 | 2026-02-27 16:00 **new PVSRA source** | 5239.496/5257.681/5220.496/5250.137 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5249.589, 5450.946] → [5257.681, 5450.946]; shrink: high 5257.681 inside → bottom 5257.681 |
| +129 | 2026-02-27 20:00 | 5250.212/5281.274/5248.519/5279.159 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5257.681, 5450.946] → [5281.274, 5450.946]; shrink: high 5281.274 inside → bottom 5281.274 |
| +130 | 2026-03-01 20:00 | 5319.152/5393.326/5314.634/5387.054 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5281.274, 5450.946] → [5393.326, 5450.946]; shrink: high 5393.326 inside → bottom 5393.326 |
| … | — | 1 unchanged bar(s) omitted | — | — |
| +132 | 2026-03-02 04:00 | 5366.257/5419.186/5340.466/5407.701 | [5112.046, 5117.625] → [5112.046, 5117.625]; already fully recovered | [5393.326, 5450.946] → [5419.186, 5450.946]; shrink: high 5419.186 inside → bottom 5419.186 |
| … | — | 895 final unchanged bar(s) omitted | — | — |

FINAL at stored-history end: BELOW FULLY_RECOVERED [5112.046, 5117.625] (updates=1, recovery=1); ABOVE REMAINING [5419.186, 5450.946] (updates=6, recovery=None).
Surviving copy age: 1026 H4 bars since creation; remaining fractions: BELOW —, ABOVE 0.094.

### Immediate next-bar outcomes in the selected copies

The 11 sources produce 22 copies. Their first completed update bar produced: fully recovered=6, shrink=16.

## Native-timeframe comparison

Each row uses its own candles and existing PVSRA; no M15 aggregation.

| Timeframe | Zones | BELOW remaining | ABOVE remaining | BELOW median recovered bars | ABOVE median recovered bars | BELOW median remaining fraction | ABOVE median remaining fraction |
|---|---:|---:|---:|---:|---:|---:|---:|
| M15 | 32566 | 395 | 121 | 1.000 | 1.000 | 0.340 | 0.274 |
| H1 | 7146 | 174 | 49 | 1.000 | 1.000 | 0.305 | 0.207 |
| H4 | 2134 | 91 | 25 | 2.000 | 2.000 | 0.291 | 0.296 |
| D1 | 1060 | 69 | 8 | 1.000 | 1.000 | 0.334 | 0.274 |

## Observations and open questions

- **Upward travel:** the 2024-04-10 20:00 source's ABOVE copy recovered on bar +1 when the next close exceeded its top; the BELOW copy first shrank and recovered on bar +3 when a later low crossed its bottom. Direction=1 and direction=0 are fixed price-coverage branches, not forecasts from the source's bullish candle.
- **Downward travel:** the 2024-04-12 00:00 source's BELOW copy shrank twice and recovered when bar +4 closed below its bottom. This source was also bullish. The 2024-04-12 08:00 bearish source had both copies recovered on bar +1 because that bar's range spanned both original boundaries.
- **Sideways overlap:** the 2024-04-12 16:00 CLIMAX source's first next bar lay inside its wide original range; its low lowered the BELOW top and its high raised the ABOVE bottom. These copies remained distinct and recovered on later bars.
- **Source direction is independent:** H4 retains 60 BELOW copies sourced from bullish candles and 21 ABOVE copies sourced from bearish candles. The bearish 2026-01-30 00:00 source leaves an ABOVE fragment of about 9.4% at the history end.
- **Long-lived fragments:** BELOW copies from 2024-05-03 and 2024-06-26 remain after 3,813 and 3,577 H4 bars, respectively. Their latest bounds are shown in examples 6–7; thousands of later bars did not satisfy `low <= bottom`. Small BELOW remnants from 2024-08-22 and 2024-09-06 retain about 3.1% and 2.1% of original height after repeated low-based shrinking. Fragment size is descriptive geometry only.
- **New activity during recovery:** the qualifying 2024-04-11 16:00 candle shrunk an older BELOW copy. On the next bar, its own independent pair was created and processed. No zone merge occurred.
- ABOVE_AVERAGE and CLIMAX follow the same recovery branches after creation. Their cross-tab counts and median lifetimes differ in this history, but no class-specific recovery rule or predictive conclusion follows.

Open research questions: how should movement away be defined before an encounter, which completed-bar information should define a return, and how should overlapping remaining fragments be presented without implying priority? No AOI, revisit, reaction, entry, or trade semantics are defined by this study.
