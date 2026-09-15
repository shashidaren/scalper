import rpyc

# 1. Connect to the container
conn = rpyc.classic.connect("localhost", 18812)

# 2. Get the MT5 module from inside the container
mt5 = conn.modules.MetaTrader5

# 3. Check account balance
if mt5.initialize():
    info = mt5.account_info()
    if info:
        print("----------------------------")
        print(f"Account: {info.login}")
        print(f"Balance: {info.balance} {info.currency}")
        print(f"Equity:  {info.equity} {info.currency}")
        print("----------------------------")
    else:
        print("Failed to get account info:", mt5.last_error())
    mt5.shutdown()
else:
    print("Failed to initialize MT5:", mt5.last_error())

conn.close()
