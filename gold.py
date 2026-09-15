import rpyc

# 1. Connect to Docker container
conn = rpyc.classic.connect("localhost", 18812)
mt5 = conn.modules.MetaTrader5

if not mt5.initialize():
    print("Failed to initialize MT5:", mt5.last_error())
    conn.close()
    exit()

# 2. Find the exact Gold symbol name used by XM
possible_names = ["GOLD", "XAUUSD", "GOLDmicro"]
gold_symbol = None

for name in possible_names:
    if mt5.symbol_info(name) is not None:
        gold_symbol = name
        break

# If not found in the list, search all available symbols
if gold_symbol is None:
    symbols = mt5.symbols_get()
    if symbols:
        for s in symbols:
            if "GOLD" in s.name.upper() or "XAU" in s.name.upper():
                gold_symbol = s.name
                break

if gold_symbol:
    # 3. Enable the symbol in Market Watch
    mt5.symbol_select(gold_symbol, True)

    # 4. Fetch live price and symbol information
    tick = mt5.symbol_info_tick(gold_symbol)
    info = mt5.symbol_info(gold_symbol)

    if tick and info:
        print("----------------------------------------")
        print(f"Symbol Name:  {gold_symbol}")
        print(f"Bid (Sell):   {tick.bid}")
        print(f"Ask (Buy):    {tick.ask}")
        print(f"Spread:       {round((tick.ask - tick.bid), info.digits)}")
        print(f"Min Lot Size: {info.volume_min}")
        print(f"Max Lot Size: {info.volume_max}")
        print("----------------------------------------")
    else:
        print(f"Could not get prices for {gold_symbol}")
else:
    print("Gold symbol not found on this server.")

mt5.shutdown()
conn.close()
