#!/usr/bin/env python3
import os
import json
import datetime
import urllib.request
import sys
import pandas as pd
import numpy as np
import joblib

# Rutas relativas a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, 'models', 'modelo_eolica_model.pkl')
CSV_HIST = os.path.join(BASE_DIR, 'data', 'historico.csv')
CSV_PRED = os.path.join(BASE_DIR, 'data', 'predicciones.csv')
JSON_PRED = os.path.join(BASE_DIR, 'data', 'prediccion_hoy.json')

PUNTOS = [
    {"nombre": "Arinaga", "lat": 27.86, "lon": -15.39},
    {"nombre": "Granadilla", "lat": 28.08, "lon": -16.50},
    {"nombre": "Fuerteventura", "lat": 28.40, "lon": -14.00},
    {"nombre": "Lanzarote", "lat": 29.00, "lon": -13.65},
]

def fetch_forecast(lat, lon):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&daily=wind_speed_10m_mean"
        f"&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def load_model():
    if os.path.exists(MODEL_PATH):
        return joblib.load(MODEL_PATH)
    from modelo_eolica import train_and_save_model
    train_and_save_model()
    return joblib.load(MODEL_PATH)

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
            for i, d in enumerate(dates):
                if d == today_str:
                    features[p['nombre']] = round(winds[i] / 3.6, 1) if winds[i] is not None else None
                    break
        except Exception:
            features[p['nombre']] = None
    return features

def predict_today(model, features):
    X = pd.DataFrame([features])[['Arinaga', 'Fuerteventura', 'Granadilla', 'Lanzarote']]
    return model.predict(X)[0]

def save_prediction(date_str, pred_pct):
    fieldnames = ['fecha', 'prediccion_eolica_pct', 'real_eolica_pct', 'error_pct']
    rows = []
    if os.path.exists(CSV_PRED):
        df = pd.read_csv(CSV_PRED)
        rows = df.to_dict('records')
    
    exists = any(str(r.get('fecha')) == str(date_str) for r in rows)
    if not exists:
        rows.append({
            'fecha': date_str,
            'prediccion_eolica_pct': round(pred_pct, 2),
            'real_eolica_pct': '',
            'error_pct': ''
        })
        df = pd.DataFrame(rows, columns=fieldnames)
        df.to_csv(CSV_PRED, index=False, lineterminator='\n')

def update_pending_predictions():
    """Revisa todas las predicciones pasadas sin valor real y los completa si ya están en historico.csv"""
    if not os.path.exists(CSV_HIST) or not os.path.exists(CSV_PRED):
        return

    df_ree = pd.read_csv(CSV_HIST)
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    eolica = df_ree[df_ree['tecnologia'] == 'Eólica'][['fecha', 'porcentaje']].copy()
    eolica['porcentaje'] = pd.to_numeric(eolica['porcentaje'])
    
    real_dict = {}
    for _, row in eolica.iterrows():
        f_str = row['fecha'].strftime('%Y-%m-%d')
        real_dict[f_str] = row['porcentaje']

    df_pred = pd.read_csv(CSV_PRED)
    updated = False

    for idx, row in df_pred.iterrows():
        f_pred = str(row['fecha'])
        real_val = row['real_eolica_pct']
        
        if (pd.isna(real_val) or str(real_val) == '' or str(real_val) == 'nan') and f_pred in real_dict:
            r_val = real_dict[f_pred]
            df_pred.at[idx, 'real_eolica_pct'] = round(r_val, 2)
            pred_val = row['prediccion_eolica_pct']
            if pd.notna(pred_val):
                df_pred.at[idx, 'error_pct'] = round(abs(pred_val - r_val), 2)
            updated = True

    if updated:
        df_pred.to_csv(CSV_PRED, index=False, lineterminator='\n')

def get_today_prediction_from_csv():
    """Lee la predicción de hoy desde data/predicciones.csv"""
    if not os.path.exists(CSV_PRED):
        return None
    df = pd.read_csv(CSV_PRED)
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    row = df[df['fecha'].astype(str) == today_str]
    if len(row) > 0:
        pred = row['prediccion_eolica_pct'].values[0]
        if pd.notna(pred) and str(pred) != '':
            return float(pred)
    return None

def get_yesterday_summary():
    """Obtiene resumen de ayer solo si el día está completo en historico.csv"""
    if not os.path.exists(CSV_PRED):
        return None, None, None
    
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # PRIMERO: verificar si ayer está en historico.csv (día completo)
    if os.path.exists(CSV_HIST):
        df_hist = pd.read_csv(CSV_HIST)
        hist_dates = df_hist['fecha'].astype(str).unique()
        if yesterday not in hist_dates:
            # Día incompleto: no calcular error
            return None, None, None
    
    # SEGUNDO: leer predicción de ayer desde CSV
    df = pd.read_csv(CSV_PRED)
    row = df[df['fecha'].astype(str) == yesterday]
    if len(row) == 0:
        return None, None, None
    
    pred = row['prediccion_eolica_pct'].values[0]
    real = row['real_eolica_pct'].values[0]
    err = row['error_pct'].values[0]
    
    if pd.notna(real) and str(real) != '' and str(real) != 'nan':
        return pred, float(real), float(err)
    else:
        return pred, None, None

def get_renewable_yesterday():
    """Obtiene % renovable de ayer desde historico.csv"""
    if not os.path.exists(CSV_HIST):
        return None
    df_ree = pd.read_csv(CSV_HIST)
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    row = df_ree[(df_ree['fecha'] == yesterday_str) & (df_ree['tecnologia'].isin(['Eólica', 'Solar fotovoltaica', 'Hidroeólica', 'Otras renovables']))]
    if len(row) == 0:
        return None
    total_ren = row['porcentaje'].sum()
    return round(float(total_ren), 2)

def calculate_mae_30d():
    """Calcula MAE de las predicciones con valor real de los últimos 30 días.
    Solo usa días completos (presentes en historico.csv).
    Devuelve tupla (mae, n_dias)"""
    if not os.path.exists(CSV_PRED) or not os.path.exists(CSV_HIST):
        return None, 0
    df = pd.read_csv(CSV_PRED)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df_hist = pd.read_csv(CSV_HIST)
    hist_dates = set(df_hist['fecha'].astype(str).unique())
    cutoff = datetime.date.today() - datetime.timedelta(days=30)
    df_recent = df[(df['fecha'] >= pd.Timestamp(cutoff)) & (df['fecha'] <= pd.Timestamp(datetime.date.today() - datetime.timedelta(days=1)))]
    # Filtrar solo filas con real, error y día completo en historico
    df_valid = df_recent.dropna(subset=['real_eolica_pct', 'error_pct'])
    df_valid = df_valid[(df_valid['real_eolica_pct'] != '') & (df_valid['error_pct'] != '')]
    # Filtrar solo días completos (en historico)
    df_valid = df_valid[df_valid['fecha'].astype(str).isin(hist_dates)]
    if len(df_valid) == 0:
        return None, 0
    mae = df_valid['error_pct'].mean()
    return round(float(mae), 2), len(df_valid)

def save_json_today(date_str, pred_pct, real_yest_pct, err_yest_pp, ren_yest_pct, mae_30d, n_dias_mae):
    """Guarda data/prediccion_hoy.json"""
    data = {
        'fecha': date_str,
        'prediccion_eolica_pct': round(pred_pct, 2) if pred_pct is not None else None,
        'real_ayer_pct': round(real_yest_pct, 2) if real_yest_pct is not None else None,
        'error_ayer_pp': round(err_yest_pp, 2) if err_yest_pp is not None else None,
        'renovable_ayer_pct': round(ren_yest_pct, 2) if ren_yest_pct is not None else None,
        'mae_30d': round(mae_30d, 2) if mae_30d is not None else None,
        'n_dias_mae': n_dias_mae if n_dias_mae is not None else 0
    }
    os.makedirs(os.path.dirname(JSON_PRED), exist_ok=True)
    with open(JSON_PRED, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    # 1. Completar cualquier predicción pendiente con datos reales disponibles
    update_pending_predictions()
    
    # 2. Predecir hoy (para guardar en CSV)
    model = load_model()
    features = get_today_forecast_wind()
    
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    pred = None
    if any(v is None for v in features.values()):
        print(f"=== Predicción Eólica para {today_str} ===")
        print("Aviso: Faltan datos de previsión meteorológica para algún punto. Predicción no guardada hoy.")
    else:
        pred = predict_today(model, features)
        save_prediction(today_str, pred)
        
        pred_yest, real_yest, err_yest = get_yesterday_summary()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Get additional data for JSON
        ren_yest = get_renewable_yesterday()
        mae_30d, n_dias_mae = calculate_mae_30d()
        
        # Leer predicción de hoy desde CSV (la guardada a las 08:15)
        pred_today = get_today_prediction_from_csv()
        
        # Save JSON
        save_json_today(today_str, pred_today, real_yest, err_yest, ren_yest, mae_30d, n_dias_mae)
        
        print(f"=== Predicción Eólica para {today_str} ===")
        print(f"Predicción % eólica hoy: {pred_today:.2f}%")
        if pred_yest is not None:
            if real_yest is not None:
                print(f"Ayer ({yesterday}): Predicción={pred_yest:.2f}% | Real={real_yest:.2f}% | Error={err_yest:.2f} p.p.")
            else:
                print(f"Ayer ({yesterday}): Predicción={pred_yest:.2f}% | Real=Incompleto (no publicado por REE).")

if __name__ == '__main__':
    main()