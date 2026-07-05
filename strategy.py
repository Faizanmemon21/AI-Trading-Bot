import numpy as np
import pandas as pd

class TradingStrategy:
    def __init__(self):
        # Stricter requirements to prevent bad trades
        self.min_confidence = 70
        
    def compute_indicators(self, df):
        """Calculates all required indicators."""
        df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        df['EMA_12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA_26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA_12'] - df['EMA_26']
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
        
        # Bollinger Bands
        df['MA_20'] = df['close'].rolling(window=20).mean()
        df['STD_20'] = df['close'].rolling(window=20).std()
        df['Upper_BB'] = df['MA_20'] + (df['STD_20'] * 2)
        df['Lower_BB'] = df['MA_20'] - (df['STD_20'] * 2)
        
        # Volume Spike
        df['Vol_MA'] = df['volume'].rolling(window=20).mean()
        df['Vol_Spike'] = df['volume'] / df['Vol_MA']
        
        return df

    def evaluate_market(self, df):
        """
        Evaluates the market and returns a signal dictionary.
        Replaces the old "buy extreme fear" logic with strict momentum confirmation.
        """
        if len(df) < 50:
            return {"action": "HOLD", "confidence": 0, "reasoning": "Not enough data"}
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 0
        reasoning = []
        
        # 1. Trend Filter (Must be in uptrend to long)
        if latest['close'] > latest['EMA_20'] and latest['EMA_20'] > latest['EMA_50']:
            score += 25
            reasoning.append("Strong Uptrend (Price > EMA20 > EMA50)")
        elif latest['close'] < latest['EMA_20']:
            # If price is below EMA20, do not even think about buying
            return {"action": "HOLD", "confidence": 0, "reasoning": "Price below EMA20, no longs allowed"}

        # 2. Momentum (MACD Crossover)
        if latest['MACD'] > latest['Signal_Line'] and prev['MACD'] <= prev['Signal_Line']:
            score += 25
            reasoning.append("Bullish MACD Crossover")
        elif latest['MACD'] > latest['Signal_Line']:
            score += 10
            reasoning.append("MACD Bullish")

        # 3. Volume Confirmation (Crucial for avoiding fakeouts)
        if latest['Vol_Spike'] > 1.5:
            score += 20
            reasoning.append(f"High Volume Confirmation ({latest['Vol_Spike']:.1f}x avg)")
        else:
            score -= 10 # Penalize low volume setups
            reasoning.append("Low Volume")

        # 4. Pullback / Bounce Entry (Instead of catching falling knives)
        # We want to buy when RSI was oversold recently but is now turning UP
        if latest['RSI'] > 40 and latest['RSI'] < 60 and prev['RSI'] < latest['RSI']:
            score += 20
            reasoning.append("RSI rising from neutral/oversold zone (Momentum turning up)")
        elif latest['RSI'] < 30:
            score -= 20 # Penalize trying to catch falling knives
            reasoning.append("RSI extremely oversold - waiting for confirmation, not catching knife")

        # 5. Bollinger Band Bounce (With trend)
        if latest['low'] <= latest['Lower_BB'] and latest['close'] > latest['Lower_BB']:
            score += 10
            reasoning.append("Bounce off Lower Bollinger Band")

        # Ensure we don't buy at the absolute top (Overbought)
        if latest['RSI'] > 70:
            score -= 30
            reasoning.append("RSI Overbought - risky entry")

        confidence = max(0, min(100, score))
        
        if confidence >= self.min_confidence:
            return {
                "action": "LONG",
                "confidence": confidence,
                "reasoning": ", ".join(reasoning),
                "stop_loss_pct": 1.5,
                "take_profit_pct": 4.5  # Better 1:3 Risk/Reward
            }
        else:
            return {
                "action": "HOLD",
                "confidence": confidence,
                "reasoning": f"Confidence too low ({confidence}). Needs {self.min_confidence}. " + ", ".join(reasoning)
            }