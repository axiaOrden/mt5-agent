from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest
from src.signals.models import CloudgazerState as S, EventType as E, SignalEvent
from src.signals.ichimoku_events import cloudgazer_ichimoku, tk_cross
from src.signals.vwap_events import broker_session_anchors, session_vwap, vwap_cross
from src.signals.candle_events import engulfing
from src.signals.cloudgazer import reduce_cloudgazer, replay_cloudgazer
from src.indicators.ichimoku import ichimoku

T = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

def event(kind):
    return SignalEvent('XAUUSDc', 'M15', T, kind)

@pytest.mark.parametrize('previous,kind,close,a,b,new,label', [
    (S.FLAT,E.VWAP_CROSS_BULLISH,5,9,9,S.LONG,'BUY'),
    (S.SHORT,E.VWAP_CROSS_BULLISH,5,9,9,S.LONG,'BUY'),
    (S.LONG,E.VWAP_CROSS_BULLISH,5,9,9,S.LONG,None),
    (S.FLAT,E.VWAP_CROSS_BEARISH,5,1,1,S.SHORT,'SELL'),
    (S.LONG,E.VWAP_CROSS_BEARISH,5,1,1,S.SHORT,'SELL'),
    (S.SHORT,E.VWAP_CROSS_BEARISH,5,1,1,S.SHORT,None),
    (S.FLAT,E.TK_CROSS_BULLISH,5,4,4,S.LONG,'BUY'),
    (S.FLAT,E.TK_CROSS_BULLISH,5,6,4,S.LONG,'WB'),
    (S.SHORT,E.TK_CROSS_BULLISH,5,9,9,S.LONG,'BUY'),
    (S.LONG,E.TK_CROSS_BULLISH,5,4,4,S.LONG,None),
    (S.FLAT,E.TK_CROSS_BEARISH,5,6,6,S.SHORT,'SELL'),
    (S.FLAT,E.TK_CROSS_BEARISH,5,4,6,S.SHORT,'WS'),
    (S.LONG,E.TK_CROSS_BEARISH,5,1,1,S.SHORT,'SELL'),
    (S.SHORT,E.TK_CROSS_BEARISH,5,6,6,S.SHORT,None),
])
def test_transitions(previous,kind,close,a,b,new,label):
    t=reduce_cloudgazer(previous,(event(kind),),close,a,b)
    assert (t.new_state,t.label,t.winning_event.event_type)==(new,label,kind)

@pytest.mark.parametrize('state,high,low', [
    (S.LONG,E.VWAP_CROSS_BULLISH,E.TK_CROSS_BEARISH),
    (S.SHORT,E.VWAP_CROSS_BEARISH,E.TK_CROSS_BULLISH),
])
def test_priority_same_direction_suppresses_opposite_tk(state,high,low):
    t=reduce_cloudgazer(state,(event(low),event(high)),5,4,6)
    assert t.new_state==state and t.label is None
    assert t.winning_event.event_type==high
    assert t.suppressed_events==(event(low),)
    assert len(t.raw_events)==2

def test_engulfing_independent():
    t=reduce_cloudgazer(S.FLAT,(event(E.BULLISH_ENGULFING),),5,4,6)
    assert t.new_state==S.FLAT and t.winning_event is None and t.raw_events
    assert engulfing(10,8,8,10)==E.BULLISH_ENGULFING
    assert engulfing(8,10,10,8)==E.BEARISH_ENGULFING
    assert engulfing(10,8,9,10) is None
    assert engulfing(8,10,9,8) is None

def test_close_ichimoku_and_history():
    df=pd.DataFrame({'close':list(range(1,54)), 'high':list(range(11,64)), 'low':list(range(0,53))})
    x=cloudgazer_ichimoku(df)
    assert pd.isna(x.tenkan.iloc[7]) and pd.isna(x.kijun.iloc[24]) and pd.isna(x.span_b.iloc[50])
    assert x.tenkan.iloc[-1]==49 and x.kijun.iloc[-1]==40.5
    assert x.span_a.iloc[-1]==44.75 and x.span_b.iloc[-1]==27.5
    assert x.tenkan.iloc[-1]!=ichimoku(df).tenkan_sen.iloc[-1]

@pytest.mark.parametrize('p_t,p_k,c_t,c_k,expected', [
    (1,1,2,1,E.TK_CROSS_BULLISH),(1,1,0,1,E.TK_CROSS_BEARISH),
    (1,2,2,1,E.TK_CROSS_BULLISH),(2,1,1,2,E.TK_CROSS_BEARISH),
    (1,1,1,1,None),(float('nan'),1,2,1,None)])
def test_tk_cross(p_t,p_k,c_t,c_k,expected):
    assert tk_cross(p_t,p_k,c_t,c_k)==expected

@pytest.mark.parametrize('p,pv,c,cv,expected', [
    (1,1,2,1,E.VWAP_CROSS_BULLISH),(1,1,0,1,E.VWAP_CROSS_BEARISH),
    (1,2,2,1,E.VWAP_CROSS_BULLISH),(2,1,1,2,E.VWAP_CROSS_BEARISH),
    (1,1,1,1,None),(1,float('nan'),2,1,None)])
def test_vwap_cross(p,pv,c,cv,expected):
    assert vwap_cross(p,pv,c,cv)==expected

def bars(n=60):
    times=[T+timedelta(minutes=15*i) for i in range(n)]
    close=[100+(i%7)*2 for i in range(n)]
    return pd.DataFrame({'time':pd.to_datetime(times,utc=True),'open':[c-1 for c in close],
        'high':[c+2 for c in close], 'low':[c-2 for c in close], 'close':close,
        'tick_volume':[1]*n,'real_volume':[100]*n})

def test_vwap_resets_and_tick_volume():
    df=bars(60)
    df.loc[0,'tick_volume']=3
    v=session_vwap(df)
    assert v.iloc[1]==pytest.approx(((100*3)+(102))/4)
    assert v.iloc[48]==pytest.approx((df.loc[48,'high']+df.loc[48,'low']+df.loc[48,'close'])/3)
    df['tick_volume']=0
    assert session_vwap(df).isna().all()

def test_vwap_uses_broker_d1_boundary_not_utc_midnight():
    df=pd.DataFrame({
        'time':pd.to_datetime(['2026-01-02 21:45Z','2026-01-02 22:00Z','2026-01-03 00:00Z']),
        'high':[100,200,300], 'low':[100,200,300], 'close':[100,200,300],
        'tick_volume':[1,3,1],
    })
    opens=pd.Series(pd.to_datetime(['2026-01-01 22:00Z','2026-01-02 22:00Z']))
    v=session_vwap(df, opens)
    assert v.tolist()==pytest.approx([100,200,225])

def test_broker_anchors_extend_closed_d1_history_for_current_session():
    daily=pd.DataFrame({'time':pd.to_datetime(['2026-01-01 22:00Z','2026-01-02 22:00Z'])})
    anchors=broker_session_anchors(daily, pd.Timestamp('2026-01-05 10:00Z'))
    assert anchors.tolist()==list(pd.to_datetime([
        '2026-01-01 22:00Z','2026-01-02 22:00Z','2026-01-03 22:00Z','2026-01-04 22:00Z']))

def test_vwap_volume_weighting_and_no_following_session_leakage():
    df=pd.DataFrame({
        'time':pd.to_datetime(['2026-01-01 22:00Z','2026-01-01 22:15Z','2026-01-02 22:00Z']),
        'high':[10,20,1000], 'low':[10,20,1000], 'close':[10,20,1000],
        'tick_volume':[1,3,999],
    })
    opens=pd.Series(pd.to_datetime(['2026-01-01 22:00Z','2026-01-02 22:00Z']))
    v=session_vwap(df, opens)
    assert v.iloc[1]==pytest.approx(17.5)
    assert v.iloc[0]==10 and v.iloc[2]==1000

def test_vwap_missing_volume_is_undefined_for_rest_of_session():
    df=bars(3)
    df.loc[1,'tick_volume']=float('nan')
    v=session_vwap(df)
    assert not pd.isna(v.iloc[0]) and pd.isna(v.iloc[1]) and pd.isna(v.iloc[2])
    assert session_vwap(df.drop(columns='tick_volume')).isna().all()

def test_d1_cloudgazer_vwap_intentionally_equals_each_bars_hlc3():
    df=pd.DataFrame({
        'time':pd.to_datetime(['2026-01-01 00:00Z','2026-01-02 00:00Z']),
        'high':[12,24], 'low':[6,12], 'close':[9,18], 'tick_volume':[10,20],
    })
    v=session_vwap(df, df['time'])
    assert v.tolist()==pytest.approx([9,18])

def test_higher_timeframe_vwap_uses_its_own_chart_bars():
    # Pine has no implicit lower-timeframe request: two H1 observations are
    # weighted directly, rather than sampling a canonical M15 VWAP.
    h1=pd.DataFrame({
        'time':pd.to_datetime(['2026-01-01 22:00Z','2026-01-01 23:00Z']),
        'high':[10,30], 'low':[10,30], 'close':[10,30], 'tick_volume':[3,1],
    })
    opens=pd.Series(pd.to_datetime(['2026-01-01 22:00Z']))
    assert session_vwap(h1,opens).iloc[-1]==pytest.approx(15)

def test_cross_across_broker_session_reset_is_preserved_like_pine():
    # ta.crossover compares consecutive series values; it does not suppress
    # the comparison just because timeframe.change("1D") reset the VWAP.
    assert vwap_cross(99,100,101,100)==E.VWAP_CROSS_BULLISH

def test_replay_determinism_and_closure():
    df=bars()
    first=replay_cloudgazer(df,'XAUUSDc','M15',broker_now=T+timedelta(minutes=15*59))
    second=replay_cloudgazer(df,'XAUUSDc','M15',broker_now=T+timedelta(minutes=15*59))
    assert first==second and len(first)==58
    assert all(t.bar_open_time<df['time'].iloc[-1] for t in first)
    assert any(t.raw_events for t in first)
