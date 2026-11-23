#!/usr/bin/env python3
import os
import json
import datetime
import urllib.request
import urllib.error
import sys
import time
import pandas as pd
import numpy as np
import joblib
import warnings
from sklearn.ensemble import RandomForestRegressor
warnings.filterwarnings('ignore')

# Rutas relativas a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_HIST = os.path.join(BASE_DIR, 'data', 'historico.csv')
CSV_PRED = os.path.join(BASE_DIR, 'data', 'predicciones.csv')
CSV_SHADOW = os.path.join(BASE_DIR, 'data', 'predicciones_sombra.csv')
JSON_PRED = os.path.join(BASE_DIR, 'data', 'prediccion_hoy.json')

PUNTOS = [
    {"nombre": "Arinaga", "lat": 27.86, "lon": -15.39},
    {"nombre": "Granadilla", "lat": 28.08, "lon": -16.50},
    {"nombre": "Fuerteventura", "lat": 28.40, "lon": -14.00},
    {"nombre": "Lanzarote", "lat": 29.00, "lon": -13.65},
]

PUNTOS_COORDS = {p["nombre"]: (p["lat"], p["lon"]) for p in PUNTOS}


def descargar_json(url):
    """Descarga JSON con hasta 3 reintentos, timeout 30s, espera 60s entre fallos."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    max_reintentos = 3
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if intento < 2:
                time.sleep(60)
            else:
                raise
    raise RuntimeError("Todos los reintentos fallaron")


def fetch_forecast(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=wind_speed_10m_mean,wind_gusts_10m_max"
        f"&timezone=UTC"
    )
    return descargar_json(url)


def get_today_forecast_wind():
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    features = {}
    for p in PUNTOS:
        try:
            data = fetch_forecast(p['lat'], p['lon'])
            daily = data.get('daily', {})
            dates = daily.get('time', [])
            winds = daily.get('wind_speed_10m_mean', [])
            gusts = daily.get('wind_gusts_10m_max', [])
            for i, d in enumerate(dates):
                if d == today_str:
                    features[f'wind_fc_{p["nombre"]}'] = round(winds[i] / 3.6, 1) if winds[i] is not None else None
                    features[f'gust_fc_{p["nombre"]}'] = round(gusts[i] / 3.6, 1) if gusts[i] is not None else None
                    if winds[i] is not None:
                        features[f'wind_fc_{p["nombre"]}_cubed'] = round((winds[i] / 3.6) ** 3, 2)
                    break
        except Exception:
            features[f'wind_fc_{p["nombre"]}'] = None
            features[f'gust_fc_{p["nombre"]}'] = None
            features[f'wind_fc_{p["nombre"]}_cubed'] = None
    return features


def load_training_data():
    """Load historical data and merge with forecast features for training."""
    # Load observed data
    df_ree = pd.read_csv(CSV_HIST)
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    eolica = df_ree[df_ree['tecnologia'] == 'Eólica'][['fecha', 'porcentaje']].copy()
    eolica['porcentaje'] = pd.to_numeric(eolica['porcentaje'])
    eolica = eolica.drop_duplicates(subset=['fecha'])

    df_meteo = pd.read_csv(os.path.join(BASE_DIR, 'data', 'meteo.csv'))
    df_meteo['fecha'] = pd.to_datetime(df_meteo['fecha'])
    meteo_pivot = df_meteo.pivot_table(index='fecha', columns='punto', values='viento_medio').reset_index()

    data_obs = pd.merge(eolica, meteo_pivot, on='fecha', how='inner').sort_values('fecha').reset_index(drop=True)
    data_obs['fecha'] = pd.to_datetime(data_obs['fecha'])

    # Load forecast data from Open-Meteo Historical Forecast API
    import urllib.request

    forecast_data = {}
    for nombre, (lat, lon) in PUNTOS_COORDS.items():
        url = f'https://historical-forecast-api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=wind_speed_10m_mean,wind_gusts_10m_max&start_date=2026-01-01&end_date=2026-11-30&timezone=UTC'
        data = descargar_json(url)
        daily = data.get('daily', {})
        df = pd.DataFrame({
            'fecha': pd.to_datetime(daily.get('time', [])),
            f'wind_fc_{nombre}': np.array(daily.get('wind_speed_10m_mean', [])) / 3.6,
            f'gust_fc_{nombre}': np.array(daily.get('wind_gusts_10m_max', [])) / 3.6
        })
        forecast_data[nombre] = df

    # Merge forecast data
    fc_merged = pd.merge(forecast_data['Arinaga'], forecast_data['Granadilla'], on='fecha')
    fc_merged = pd.merge(fc_merged, forecast_data['Fuerteventura'], on='fecha')
    fc_merged = pd.merge(fc_merged, forecast_data['Lanzarote'], on='fecha')

    # Merge observed + forecast
    puntos = ['Arinaga', 'Granadilla', 'Fuerteventura', 'Lanzarote']
    data_obs = eolica.merge(meteo_pivot, on='fecha', how='inner').sort_values('fecha').reset_index(drop=True)
    data_obs['fecha'] = pd.to_datetime(data_obs['fecha'])

    data = pd.merge(data_obs[['fecha', 'porcentaje'] + ['Arinaga', 'Granadilla', 'Fuerteventura', 'Lanzarote']], fc_merged, on='fecha', how='inner')
    data['fecha'] = pd.to_datetime(data['fecha'])
    data = data.sort_values('fecha').reset_index(drop=True)

    # Add cubed features
    for p in ['Arinaga', 'Granadilla', 'Fuerteventura', 'Lanzarote']:
        if f'wind_fc_{p}' in data.columns:
            data[f'wind_fc_{p}_cubed'] = data[f'wind_fc_{p}'] ** 3

    return data


def load_shadow_csv():
    """Load or create shadow predictions CSV."""
    if os.path.exists(CSV_SHADOW):
        df = pd.read_csv(CSV_SHADOW)
        df['fecha'] = pd.to_datetime(df['fecha'])
        return df
    return pd.DataFrame(columns=['fecha', 'prediccion', 'real', 'error'])


def save_shadow_csv(df):
    df.to_csv(CSV_SHADOW, index=False, lineterminator='\n')


def update_pending_predictions():
    """Update shadow predictions with real values when available."""
    if not os.path.exists(CSV_HIST) or not os.path.exists(CSV_SHADOW):
        return

    df_ree = pd.read_csv(CSV_HIST)
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    eolica = df_ree[df_ree['tecnologia'] == 'Eólica'][['fecha', 'porcentaje']].copy()
    eolica['porcentaje'] = pd.to_numeric(eolica['porcentaje'])

    real_dict = {}
    for _, row in eolica.iterrows():
        f_str = row['fecha'].strftime('%Y-%m-%d')
        real_dict[f_str] = row['porcentaje']

    df_shadow = pd.read_csv(CSV_SHADOW)
    df_shadow['fecha'] = pd.to_datetime(df_shadow['fecha'])
    updated = False

    for idx, row in df_shadow.iterrows():
        f_pred = row['fecha'].strftime('%Y-%m-%d')
        real_val = row['real']
        if (pd.isna(real_val) or str(real_val) == '' or str(real_val) == 'nan') and f_pred in real_dict:
            r_val = real_dict[f_pred]
            df_shadow.at[idx, 'real'] = round(r_val, 2)
            pred_val = row['prediccion']
            if pd.notna(pred_val):
                df_shadow.at[idx, 'error'] = round(pred_val - r_val, 2)
            updated = True

    if updated:
        df_shadow.to_csv(CSV_SHADOW, index=False, lineterminator='\n')


def get_yesterday_summary():
    """Get yesterday's prediction and real value if available."""
    if not os.path.exists(CSV_SHADOW):
        return None, None, None

    df = pd.read_csv(CSV_SHADOW)
    df['fecha'] = pd.to_datetime(df['fecha'])
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')

    # Check if yesterday is in historico (complete day)
    if os.path.exists(CSV_HIST):
        df_hist = pd.read_csv(CSV_HIST)
        df_hist['fecha'] = pd.to_datetime(df_hist['fecha'])
        hist_dates = df_hist['fecha'].dt.strftime('%Y-%m-%d').unique()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        if yesterday not in df_hist['fecha'].dt.strftime('%Y-%m-%d').values:
            return None, None, None

    df_shadow = pd.read_csv(CSV_SHADOW)
    df_shadow['fecha'] = pd.to_datetime(df_shadow['fecha'])
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    row = df_shadow[df_shadow['fecha'].astype(str) == yesterday]
    if len(row) == 0:
        return None, None, None

    pred = row['prediccion'].values[0]
    real = row['real'].values[0]
    err = row['error'].values[0]

    if pd.notna(real) and str(real) != '' and str(real) != 'nan':
        return pred, float(real), float(err)
    else:
        return pred, None, None


def save_shadow_prediction(date_str, pred_pct):
    """Save prediction to shadow CSV."""
    fieldnames = ['fecha', 'prediccion', 'real', 'error']
    rows = []
    if os.path.exists(CSV_SHADOW):
        df = pd.read_csv(CSV_SHADOW)
        rows = df.to_dict('records')

    exists = any(str(r.get('fecha')) == str(date_str) for r in rows)
    if not exists:
        rows.append({
            'fecha': date_str,
            'prediccion': round(pred_pct, 2),
            'real': '',
            'error': ''
        })
        df = pd.DataFrame(rows, columns=fieldnames)
        df.to_csv(CSV_SHADOW, index=False, lineterminator='\n')


def main():
    try:
        # 1. Update pending predictions with real values
        update_pending_predictions()

        # 2. Predict today
        data = load_training_data()

        # Features: forecast wind + gust_max + cubed
        features = [c for c in data.columns if c.startswith('wind_fc_') or c.startswith('gust_fc_') or c.endswith('_cubed')]

        today_str = datetime.date.today().strftime('%Y-%m-%d')

        # Get today's forecast
        features_today = get_today_forecast_wind()

        if any(v is None for v in features_today.values()):
            print(f"=== Predicción Sombra para {today_str} ===")
            print("Aviso: Open-Meteo no responde, predicción sombra no guardada hoy")
            return

        # Train RandomForest on last 60 days (until D-1)
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        train_end = yesterday
        train_start = train_end - datetime.timedelta(days=59)

        train_data = data[(data['fecha'] >= pd.Timestamp(train_start)) & (data['fecha'] <= pd.Timestamp(train_end))].copy()

        if len(train_data) < 30:
            today_str = datetime.date.today().strftime('%Y-%m-%d')
            print(f"=== Predicción Sombra para {today_str} ===")
            print(f"Aviso: Solo {len(train_data)} días de entrenamiento (mínimo 30). Predicción no guardada.")
            return

        features = [c for c in data.columns if c.startswith('wind_fc_') or c.startswith('gust_fc_') or c.endswith('_cubed')]
        X_train = train_data[features]
        y_train = train_data['porcentaje']

        model = RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)

        # Predict today - ensure same feature order
        X_today = pd.DataFrame([features_today])
        X_today = X_today[features]  # same order as training
        pred = model.predict(X_today)[0]

        today_str = datetime.date.today().strftime('%Y-%m-%d')
        save_shadow_prediction(today_str, pred)

        pred_yest, real_yest, err_yest = get_yesterday_summary()

        print(f"=== Predicción Sombra para {today_str} ===")
        print(f"Predicción % eólica hoy: {pred:.2f}%")
        if pred_yest is not None:
            if real_yest is not None:
                print(f"Ayer: Predicción={pred_yest:.2f}% | Real={real_yest:.2f}% | Error={err_yest:.2f} pp.")
            else:
                print(f"Ayer: Predicción={pred_yest:.2f}% | Real=Pendiente de publicación por REE.")
    except (urllib.error.URLError, TimeoutError, OSError):
        today_str = datetime.date.today().strftime('%Y-%m-%d')
        print(f"=== Predicción Sombra para {today_str} ===")
        print("Aviso: Open-Meteo no responde, predicción sombra no guardada hoy")


if __name__ == '__main__':
    main()