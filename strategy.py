import pandas as pd

class ScalpStrategy:
    def __init__(self):
        pass

    def check_signal(self, rates):
        if rates is None or len(rates) < 200:
            return None, 0, 0

        df = pd.DataFrame(rates)
        
        # 1. Trend Filter: 200 EMA
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        # 2. RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # 3. ATR (14) Volatility
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        current_close = df['close'].iloc[-1]
        current_ema = df['ema200'].iloc[-1]
        current_atr = df['atr'].iloc[-1]
        
        rsi_curr = df['rsi'].iloc[-1]
        rsi_prev = df['rsi'].iloc[-2]

        # Minimum volatility filter ($0.50 per min)
        if current_atr < 0.50:
            return None, 0, 0

        # Dynamic SL & TP based on market volatility
        sl_dist = current_atr * 2.0
        tp_dist = current_atr * 5.0

        # BUY: Uptrend + Deep RSI Bounce (< 28)
        if current_close > current_ema and rsi_prev <= 28 and rsi_curr > 28:
            return "BUY", sl_dist, tp_dist

        # SELL: Downtrend + Deep RSI Reversal (> 72)
        elif current_close < current_ema and rsi_prev >= 72 and rsi_curr < 72:
            return "SELL", sl_dist, tp_dist

        return None, 0, 0
