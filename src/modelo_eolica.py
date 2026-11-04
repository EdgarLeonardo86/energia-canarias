#!/usr/bin/env python3
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import joblib
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error

# Rutas relativas a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_HIST = os.path.join(BASE_DIR, 'data', 'historico.csv')
CSV_METEO = os.path.join(BASE_DIR, 'data', 'meteo.csv')
GRAF_DIR = os.path.join(BASE_DIR, 'graficas')
MODEL_DIR = os.path.join(BASE_DIR, 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'modelo_eolica_model.pkl')

def train_and_save_model():
    # 1. Cargar datos
    if not os.path.exists(CSV_HIST) or not os.path.exists(CSV_METEO):
        print("Ficheros CSV no encontrados.")
        return None

    df_ree = pd.read_csv(CSV_HIST)
    df_meteo = pd.read_csv(CSV_METEO)

    # 2. Validación previa (ANALISTA.md): sin ceros, huecos ni duplicados
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    df_meteo['fecha'] = pd.to_datetime(df_meteo['fecha'])

    # Extraer % eólica diario
    eolica = df_ree[df_ree['tecnologia'] == 'Eólica'][['fecha', 'porcentaje']].copy()
    eolica['porcentaje'] = pd.to_numeric(eolica['porcentaje'])
    eolica = eolica.drop_duplicates(subset=['fecha'])

    # Pivotar meteo para tener columnas por punto (viento_medio)
    meteo_pivot = df_meteo.pivot_table(index='fecha', columns='punto', values='viento_medio').reset_index()

    # Combinar
    data = pd.merge(eolica, meteo_pivot, on='fecha').sort_values('fecha').reset_index(drop=True)

    # Comprobar ceros / nulos
    if data.isnull().any().any():
        data = data.dropna()

    print(f"Periodo total disponible en dataset combinado: {data['fecha'].min().strftime('%Y-%m-%d')} al {data['fecha'].max().strftime('%Y-%m-%d')} ({len(data)} días)")

    # Puntos eólicos disponibles
    puntos = [col for col in meteo_pivot.columns if col != 'fecha']
    print(f"Puntos meteorológicos utilizados como features: {puntos}")

    # 3. Conjuntos de entrenamiento (Enero - Agosto) y validación (Septiembre - Octubre)
    train_mask = (data['fecha'] >= '2026-01-01') & (data['fecha'] <= '2026-08-31')
    val_mask = (data['fecha'] >= '2026-09-01') & (data['fecha'] <= '2026-10-31')

    train_data = data[train_mask]
    val_data = data[val_mask]

    print(f"Entrenamiento (Ene-Ago): {len(train_data)} días")
    print(f"Validación (Sep-Oct): {len(val_data)} días")

    X_train = train_data[puntos]
    y_train = train_data['porcentaje']

    X_val = val_data[puntos]
    y_val = val_data['porcentaje']

    # 4. Entrenar Regresión Lineal
    model = LinearRegression()
    model.fit(X_train, y_train)

    # Guardar modelo en models/
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"Modelo guardado en: {MODEL_PATH}")

    # 5. Predicción y métricas en validación
    y_pred = model.predict(X_val)

    r2 = r2_score(y_val, y_pred)
    mae = mean_absolute_error(y_val, y_pred)

    print(f"\n--- RESULTADOS VALIDACIÓN (Sep-Oct 2026) ---")
    print(f"R²: {r2:.4f}")
    print(f"MAE: {mae:.2f}%")

    # 6. Gráfica comparativa
    os.makedirs(GRAF_DIR, exist_ok=True)
    plt.figure(figsize=(10, 5))
    plt.plot(val_data['fecha'], y_val, label='Real (% Eólica)', marker='o', color='tab:blue', alpha=0.7)
    plt.plot(val_data['fecha'], y_pred, label='Predicción Modelo', marker='x', color='tab:orange', linestyle='--', linewidth=2)
    plt.title('Validación Modelo Eólica: Real vs Predicción (Sep-Oct 2026)')
    plt.xlabel('Fecha')
    plt.ylabel('% Eólica sobre Total')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gca().xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=30)
    plt.tight_layout()
    
    chart_path = os.path.join(GRAF_DIR, 'validacion_modelo_eolica.png')
    plt.savefig(chart_path, dpi=300)
    plt.close()
    print(f"Gráfica guardada en: {chart_path}")
    
    return model

def main():
    train_and_save_model()

if __name__ == '__main__':
    main()