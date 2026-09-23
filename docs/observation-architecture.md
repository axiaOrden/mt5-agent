# Observation architecture

The project records market facts before interpreting combinations or deciding
whether to trade. A disagreement between observations is retained as research
data; it does not invalidate either observation.

| Component | Current responsibility | Status |
|---|---|---|
| Standard Ichimoku and market state | Describe structural price context, including cloud location, Kijun/Tenkan/Chikou relationships, direction, and condition | Implemented; existing formulas and market-state meanings retained |
| Session VWAP | Broker D1-anchored, chart-timeframe price reference and input to the existing Cloudgazer state machine | Implemented; audited behavior retained |
| PVSRA | Classify unusual candle activity and record that candle's direction and measurement provenance | Implemented; candle direction is an observation, not a forecast |
| Cloudgazer | Record its own raw events, state changes, and BUY/SELL/WB/WS labels | Implemented; labels describe that state machine, not a final trading decision |
| Multi-timeframe context | Preserve native-timeframe structure, states, roles, and descriptive alignments at a causal cutoff | Implemented; alignment does not filter events or score them |
| Historical replay and cohort analysis | Preserve events, independent PVSRA/context facts, saved forward outcomes, and descriptive group statistics | Implemented; `research-analyze` reads only its saved event Parquet |
| VCZ | Remember locations of qualifying PVSRA activity; later study movement away, return, and reaction | **DESIGN PENDING** for Candidate, Active, Revisited/Area of Interest, and Invalidated lifecycle definitions |
| Execution | Evaluate entries, stops, targets, and sizing only after separate research and design | Not implemented |

The intended research sequence is structure → activity → location memory →
price movement and return → observed reaction. The arrows describe questions
to study, not mandatory gates. A bullish PVSRA candle can coexist with
bearish Ichimoku structure; a Cloudgazer BUY label can coexist with price
below the Kumo. The persisted fields preserve those combinations.

`PRIMARY_HIGHER` is an existing relative role in the MTF context schema; it
does not designate H4 as a universally preferred PVSRA or future VCZ
timeframe. PVSRA is calculated separately from M15, H1, H4, and D1 bars.
No PVSRA class implies BUY/SELL, and no alignment value implies a superior
signal. The analyst chooses explicit cohorts; the software does not rank or
recommend them.

Current `research-analyze` statistics, Cloudgazer event labels, and alignment
fields remain historical observations. The definitions for activating or
revisiting a future VCZ have not been chosen and must not be inferred from a
Pine box's drawing or recovery behavior.
