"""
AI Price Recommendation
------------------------
Trains a lightweight Gradient Boosting Regressor on category/quantity/
quality/season data (data/base_prices.csv) to predict a fair market
price per kg, then personalizes it using the farmer's own historical
average sale price for that crop (if any exists in the DB).

This is intentionally a small, fast, explainable model -- swap in a
larger model / real mandi price feed API later without changing the
calling code (recommend_price stays the same signature).
"""
import os
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "base_prices.csv")

_model = None


def _train():
    global _model
    df = pd.read_csv(CSV_PATH)
    X = df[["category", "quantity_kg", "quality_score", "season_factor"]]
    y = df["price_per_kg"]

    pre = ColumnTransformer(
        transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), ["category"])],
        remainder="passthrough",
    )
    pipe = Pipeline([
        ("pre", pre),
        ("gbr", GradientBoostingRegressor(n_estimators=150, max_depth=3, random_state=42)),
    ])
    pipe.fit(X, y)
    _model = pipe
    return _model


def get_model():
    global _model
    if _model is None:
        _model = _train()
    return _model


def current_season_factor():
    """Very small seasonality proxy - can be replaced with real mandi
    seasonality data. Cycles gently through the year."""
    import datetime
    month = datetime.datetime.now().month
    # Harvest-heavy months (rabi/kharif) push prices slightly down,
    # lean months slightly up.
    table = {1: 0.95, 2: 0.95, 3: 1.0, 4: 1.0, 5: 1.05, 6: 1.05,
             7: 1.1, 8: 1.05, 9: 1.0, 10: 0.95, 11: 0.9, 12: 0.9}
    return table.get(month, 1.0)


def recommend_price(category, quantity_kg, quality_score, farmer_history_avg=None):
    """Returns dict with base AI price, adjusted price band, and confidence."""
    model = get_model()
    season = current_season_factor()
    row = pd.DataFrame([{
        "category": category,
        "quantity_kg": quantity_kg,
        "quality_score": quality_score,
        "season_factor": season,
    }])
    base_price = float(model.predict(row)[0])

    # Personalize using the farmer's own past sales, if we have them --
    # this is what differentiates it from a plain "market average" feed.
    if farmer_history_avg:
        adjusted = 0.7 * base_price + 0.3 * farmer_history_avg
        confidence = 0.85
    else:
        adjusted = base_price
        confidence = 0.65

    low = round(adjusted * 0.9, 2)
    high = round(adjusted * 1.1, 2)

    return {
        "suggested_price": round(adjusted, 2),
        "price_band_low": low,
        "price_band_high": high,
        "confidence": confidence,
        "season_factor": season,
    }
