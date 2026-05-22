import json
import joblib
import numpy as np
import pandas as pd
import geopandas as gpd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_predict
from sklearn.metrics import mean_squared_error, r2_score

from pipeline.load_and_clean import PROJECT_ROOT

GEOJSON_PATH = PROJECT_ROOT / "output" / "master.geojson"
MODEL_PATH = PROJECT_ROOT / "output" / "demographic_model.joblib"
METADATA_PATH = PROJECT_ROOT / "output" / "demographic_model.json"

DEMOGRAPHIC_FEATURES = [
    "median_income",
    "mean_commute_time",
    "poverty_rate",
    "pct_black",
    "pct_hispanic",
    "pct_foreign_born",
    "rent_burden",
    "unemployment_rate",
    "pct_bachelors",
    # Building-stock features (PLUTO). Old buildings legitimately produce more
    # heat/plumbing complaints regardless of who lives in them; including
    # these so age-of-stock isn't conflated with city neglect in the residual.
    "median_year_built",
    "pct_prewar_units",
    # Rent-stabilization proxy: pre-1974 buildings with 6+ units (ETPA threshold).
    # Captures landlord-incentive structure independent of tenant demographics.
    "pct_rent_stab_proxy",
]


def load_scored() -> pd.DataFrame:
    gdf = gpd.read_file(GEOJSON_PATH)
    return pd.DataFrame(gdf.drop(columns="geometry"))


def correlation_report(df: pd.DataFrame):
    cols = [c for c in DEMOGRAPHIC_FEATURES if c in df.columns]
    corr = df[cols + ["risk_score"]].corr(numeric_only=True)["risk_score"].drop("risk_score")
    print("\n=== Pearson correlation with risk_score ===")
    print(corr.sort_values(key=lambda s: s.abs(), ascending=False).round(3))
    return corr


def train_model(df: pd.DataFrame):
    features = [c for c in DEMOGRAPHIC_FEATURES if c in df.columns]
    data = df[features + ["risk_score"]].dropna()
    print(f"\nTraining on {len(data):,} tracts with complete demographic data")

    X = data[features].values
    y = data["risk_score"].values
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=3,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

    print("\n=== Random Forest performance ===")
    print(f"  R²:   {r2:.3f}")
    print(f"  RMSE: {rmse:.2f}")

    importance = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
    print("\n=== Feature importance ===")
    print(importance.round(3))

    # Store min/max per feature so the UI slider has sensible ranges
    feature_ranges = {
        f: {
            "min": float(data[f].min()),
            "max": float(data[f].max()),
            "median": float(data[f].median()),
        }
        for f in features
    }

    joblib.dump(model, MODEL_PATH)
    metadata = {
        "features": features,
        "r2": float(r2),
        "rmse": rmse,
        "importance": importance.to_dict(),
        "feature_ranges": feature_ranges,
    }
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"\nSaved model → {MODEL_PATH}")
    print(f"Saved metadata → {METADATA_PATH}")
    return model, metadata


def export_residuals(model, features):
    """Cross-validated predictions → residual = actual - predicted.

    Positive residual = tract is *more* underserved than its demographics predict
    (unexplained neglect). Negative = less underserved than expected.
    """
    gdf = gpd.read_file(GEOJSON_PATH)
    subset = gdf[["GEOID", "risk_score"] + features].dropna()
    fresh = RandomForestRegressor(**model.get_params())
    preds = cross_val_predict(
        fresh,
        subset[features].values,
        subset["risk_score"].values,
        cv=5,
        n_jobs=-1,
    )
    subset = subset.assign(
        predicted_risk=preds,
        risk_residual=subset["risk_score"].values - preds,
    )

    print("\n=== Residual distribution (actual - predicted) ===")
    print(subset["risk_residual"].describe().round(2))

    for col in ("predicted_risk", "risk_residual"):
        if col in gdf.columns:
            gdf = gdf.drop(columns=col)
    gdf = gdf.merge(
        subset[["GEOID", "predicted_risk", "risk_residual"]],
        on="GEOID", how="left",
    )
    gdf.to_file(GEOJSON_PATH, driver="GeoJSON")
    print(f"Wrote predicted_risk + risk_residual to {GEOJSON_PATH}")

    top = subset.nlargest(10, "risk_residual")[
        ["GEOID", "risk_score", "predicted_risk", "risk_residual"]
    ]
    print("\nTop 10 tracts with the most *unexplained* neglect:")
    print(top.round(2).to_string(index=False))


if __name__ == "__main__":
    df = load_scored()
    correlation_report(df)
    model, metadata = train_model(df)
    export_residuals(model, metadata["features"])
