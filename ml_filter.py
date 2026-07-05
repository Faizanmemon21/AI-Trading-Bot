"""
ML Filter — Loads model.pkl and gates trade entries
Stage 6: Better logging, confidence threshold from CONFIG
"""

import logging
import os
import numpy as np

log = logging.getLogger("ml_filter")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


class MLFilter:
    def __init__(self):
        self._bundle = None
        self._available = False
        self._load()

    def _load(self):
        """Attempts to load the pre-trained model."""
        if not os.path.exists(MODEL_PATH):
            log.info("⚠️  model.pkl not found — ML filter DISABLED. Bot runs on indicator logic only.")
            return
        
        try:
            import joblib
            self._bundle = joblib.load(MODEL_PATH)
            self._available = True
            
            # Extract model metadata
            accuracy = self._bundle.get("test_accuracy", "?")
            auc = self._bundle.get("test_auc", "?")
            trained_on = self._bundle.get("trained_on", "?")
            n_features = len(self._bundle.get("feature_cols", []))
            
            log.info(
                f"✅ ML model loaded successfully!\n"
                f"   • Trained on: {trained_on}\n"
                f"   • Test accuracy: {accuracy}%\n"
                f"   • Test AUC: {auc}\n"
                f"   • Features: {n_features}"
            )
        except ImportError:
            log.warning("joblib not installed — ML filter disabled. Install: pip install joblib")
        except Exception as e:
            log.warning(f"ML model load failed: {e} — filter disabled.")

    @property
    def available(self) -> bool:
        """Returns True if model is loaded and ready."""
        return self._available

    def predict(self, indicators: dict) -> float:
        """
        Takes the indicators dict and returns the ensemble WIN probability (0.0–1.0).
        
        This is the probability that the NEXT trade on this setup will be profitable.
        
        Returns 0.5 (neutral) if model not loaded or features missing.
        """
        if not self._available or self._bundle is None:
            return 0.5

        try:
            feat_cols = self._bundle.get("feature_cols", [])
            row = self._build_feature_row(indicators, feat_cols)
            
            if row is None:
                log.debug("Failed to build feature row for ML prediction")
                return 0.5

            X = np.array([row])
            X_s = self._bundle["scaler"].transform(X)

            # Ensemble: average of Random Forest and XGBoost
            rf_model = self._bundle.get("rf")
            xgb_model = self._bundle.get("xgb")
            
            if rf_model and xgb_model:
                rf_p = rf_model.predict_proba(X_s)[0][1]
                xgb_p = xgb_model.predict_proba(X_s)[0][1]
                prob = (rf_p + xgb_p) / 2.0
            elif rf_model:
                prob = rf_model.predict_proba(X_s)[0][1]
            elif xgb_model:
                prob = xgb_model.predict_proba(X_s)[0][1]
            else:
                return 0.5
            
            return float(prob)

        except Exception as e:
            log.warning(f"ML predict error: {e}")
            return 0.5

    def _build_feature_row(self, ind: dict, feat_cols: list) -> list | None:
        """
        Maps indicator keys from market_data['indicators'] into the feature vector
        that the model expects.
        """
        from datetime import datetime, timezone

        try:
            hour = datetime.now(timezone.utc).hour

            # Feature mapping — align with how the model was trained
            mapping = {
                # Price vs moving averages
                "rsi": ind.get("rsi", 50),
                "macd": ind.get("macd", 0),
                "macd_hist": ind.get("macd_hist", 0),
                "macd_rising": 1 if (ind.get("macd_hist", 0) or 0) > (ind.get("macd_hist_prev", 0) or 0) else 0,
                
                # EMA ratios
                "price_vs_ema20": ((ind.get("close", 1) / ind.get("ema20", 1)) - 1) * 100 if ind.get("ema20") else 0,
                "price_vs_ema50": ((ind.get("close", 1) / ind.get("ema50", 1)) - 1) * 100 if ind.get("ema50") else 0,
                "price_vs_ema200": ((ind.get("close", 1) / ind.get("ema200", 1)) - 1) * 100 if ind.get("ema200") else 0,
                "ema20_vs_ema50": ((ind.get("ema20", 1) / ind.get("ema50", 1)) - 1) * 100 if ind.get("ema50") else 0,
                
                # Volatility
                "bb_width": ind.get("bb_width", 1.0),
                "bb_pos": ind.get("bb_pos", 0.5),
                "atr_pct": ind.get("atr_pct", 1.0),
                
                # Momentum
                "stoch_rsi": ind.get("stoch_k", 50),
                "obv_rising": 1 if ind.get("obv_trend") == "rising" else 0,
                "adx": ind.get("adx", 20),
                "trending": 1 if (ind.get("adx", 0) or 0) > 25 else 0,
                
                # Volume
                "vol_ratio": ind.get("vol_ratio", 1.0),
                
                # Returns (lookback)
                "ret_1h": ind.get("ret_1h", 0),
                "ret_4h": ind.get("ret_4h", 0),
                "ret_12h": ind.get("ret_12h", 0),
                "ret_24h": ind.get("ret_24h", 0),
                
                # Candle structure
                "body_size": ind.get("body_size", 0),
                "upper_wick": ind.get("upper_wick", 0),
                "lower_wick": ind.get("lower_wick", 0),
                "bullish_candle": 1 if ind.get("bullish_candle") else 0,
                
                # Session timing
                "in_session": 1 if 7 <= hour < 17 else 0,
            }

            # Build feature row in the order the model expects
            row = []
            for col in feat_cols:
                val = mapping.get(col)
                if val is None:
                    log.debug(f"Missing feature '{col}' — using 0")
                    val = 0
                row.append(float(val))

            return row

        except Exception as e:
            log.warning(f"Feature row build error: {e}")
            return None
