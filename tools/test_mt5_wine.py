import MetaTrader5 as mt5

TERMINAL = r"Z:\home\heaxia\App\exe\fx\mt5\terminal64.exe"

print(f"MetaTrader5: {mt5.__version__}")

if not mt5.initialize(path=TERMINAL):
    print(f"Connection failed: {mt5.last_error()}")
    raise SystemExit(1)

print("MT5 connection: OK")

terminal = mt5.terminal_info()
account = mt5.account_info()

if account is None:
    print(f"Account unavailable: {mt5.last_error()}")
    mt5.shutdown()
    raise SystemExit(1)

print()
print("ACCOUNT")
print("=======")
print(f"Login:        {account.login}")
print(f"Server:       {account.server}")
print(f"Currency:     {account.currency}")
print(f"Leverage:     1:{account.leverage}")
print(f"Balance:      {account.balance}")
print(f"Equity:       {account.equity}")
print(f"Profit:       {account.profit}")
print(f"Margin:       {account.margin}")
print(f"Free Margin:  {account.margin_free}")
print(f"Margin Level: {account.margin_level}")

positions = mt5.positions_get()

print()
print("POSITIONS")
print("=========")

if positions is None:
    print(f"Unable to retrieve positions: {mt5.last_error()}")
elif not positions:
    print("No open positions.")
else:
    for p in positions:
        side = "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"

        print(
            f"#{p.ticket} "
            f"{p.symbol} "
            f"{side} "
            f"{p.volume} "
            f"entry={p.price_open} "
            f"current={p.price_current} "
            f"profit={p.profit}"
        )

mt5.shutdown()
