import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os

st.set_page_config(page_title="Generación Eléctrica Canarias", layout="wide")

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
GRAF_DIR = os.path.join(os.path.dirname(__file__), 'graficas')

# Cargar datos
@st.cache_data
def load_data():
    historico = pd.read_csv(os.path.join(DATA_DIR, 'historico.csv'))
    historico['fecha'] = pd.to_datetime(historico['fecha'])
    historico['mwh'] = pd.to_numeric(historico['mwh'])
    historico['total_mwh'] = pd.to_numeric(historico['total_mwh'])
    historico['porcentaje_renovable'] = pd.to_numeric(historico['porcentaje_renovable'])
    return historico

@st.cache_data
def load_meteo():
    meteo = pd.read_csv(os.path.join(DATA_DIR, 'meteo.csv'))
    meteo['fecha'] = pd.to_datetime(meteo['fecha'])
    meteo['viento_medio'] = pd.to_numeric(meteo['viento_medio'])
    return meteo

@st.cache_data
def load_predicciones():
    path = os.path.join(DATA_DIR, 'predicciones.csv')
    if os.path.exists(path):
        df = pd.read_csv(path)
        df['fecha'] = pd.to_datetime(df['fecha'])
        for col in ['prediccion_eolica_pct', 'real_eolica_pct', 'error_pct']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    return pd.DataFrame(columns=['fecha', 'prediccion_eolica_pct', 'real_eolica_pct', 'error_pct'])

historico = load_data()
meteo = load_meteo()
predicciones = load_predicciones()

# Daily % renovable
daily = historico[['fecha', 'total_mwh', 'porcentaje_renovable']].drop_duplicates(subset=['fecha']).sort_values('fecha').reset_index(drop=True)

# Sidebar
st.sidebar.title("Filtros")
max_date = daily['fecha'].max()
min_date = daily['fecha'].min()
date_range = st.sidebar.date_input("Rango de fechas", value=(max_date - pd.Timedelta(days=90), max_date), min_value=min_date, max_value=max_date)

if len(date_range) == 2:
    start_date, end_date = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
else:
    start_date, end_date = max_date - pd.Timedelta(days=90), max_date

daily_filt = daily[(daily['fecha'] >= start_date) & (daily['fecha'] <= end_date)].copy()
daily_filt['ma_7'] = daily_filt['porcentaje_renovable'].rolling(window=7).mean()

# === 1. % Renovable últimos 90 días ===
st.header("1. Evolución del % Renovable Diario")
fig1, ax1 = plt.subplots(figsize=(10, 4))
ax1.plot(daily_filt['fecha'], daily_filt['porcentaje_renovable'], label='% Renovable Diario', alpha=0.5, color='tab:green')
ax1.plot(daily_filt['fecha'], daily_filt['ma_7'], label='Media Móvil 7 días', color='darkgreen', linewidth=2)
ax1.set_xlabel('Fecha')
ax1.set_ylabel('% Renovable')
ax1.grid(True, linestyle='--', alpha=0.6)
ax1.legend()
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
ax1.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
plt.xticks(rotation=30)
plt.tight_layout()
st.pyplot(fig1)

# === 2. Mix por semanas naturales ===
st.header("2. Mix Tecnológico por Semanas Naturales")
st.caption("Semanas lunes-domingo. Renovables agrupadas arriba (verdes/amarillos), fósiles abajo (grises/marrones).")

# Semanas naturales en el rango
weeks = []
df_weeks = historico.copy()
current_sunday = daily_filt['fecha'].max()
while current_sunday >= daily_filt['fecha'].min():
    monday = current_sunday - pd.Timedelta(days=6)
    label = f"{monday.strftime('%d/%m')} - {current_sunday.strftime('%d/%m')}"
    mask = (df_weeks['fecha'] >= monday) & (df_weeks['fecha'] <= current_sunday)
    df_weeks.loc[mask, 'semana_label'] = label
    weeks.append(label)
    current_sunday = monday - pd.Timedelta(days=1)

weeks = list(reversed(weeks))
if weeks:
    pivot_mix = df_weeks[df_weeks['semana_label'].notna()].pivot_table(
        index='semana_label', columns='tecnologia', values='mwh', aggfunc='sum')
    pivot_mix = pivot_mix.reindex(weeks)
    pivot_mix_pct = pivot_mix.div(pivot_mix.sum(axis=1), axis=0) * 100

    fossil = [t for t in pivot_mix_pct.columns if t in ['Ciclo combinado', 'Motores diésel', 'Turbina de vapor', 'Turbina de gas']]
    renewable = [t for t in pivot_mix_pct.columns if t not in fossil]
    ordered = fossil + renewable
    pivot_mix_pct = pivot_mix_pct[ordered]

    colors = {
        'Ciclo combinado': '#4d4d4d', 'Motores diésel': '#8c6239',
        'Turbina de vapor': '#7f7f7f', 'Turbina de gas': '#b58958',
        'Otras renovables': '#c7e9c0', 'Hidroeólica': '#74c476',
        'Solar fotovoltaica': '#ffeda0', 'Eólica': '#238b45'
    }
    bar_colors = [colors.get(t, '#cccccc') for t in ordered]

    fig2, ax2 = plt.subplots(figsize=(10, 4))
    pivot_mix_pct.plot(kind='bar', stacked=True, ax=ax2, color=bar_colors)
    ax2.set_xlabel('Semana (Lun - Dom)')
    ax2.set_ylabel('% Generación')
    ax2.set_xticklabels(ax2.get_xticklabels(), rotation=15)
    ax2.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax2.grid(axis='y', linestyle='--', alpha=0.6)
    plt.tight_layout()
    st.pyplot(fig2)

# === 3. Predicción vs Real Eólica ===
st.header("3. Predicción Eólica vs Valor Real")
st.caption("Predicción diaria a partir de forecast de viento (4 puntos) con modelo de regresión lineal (R²=0.90, MAE=2.18%).")

if not predicciones.empty:
    pred_filt = predicciones[(predicciones['fecha'] >= start_date) & (predicciones['fecha'] <= end_date)].copy()
    
    fig3, ax3 = plt.subplots(figsize=(10, 4))
    # Real
    real_data = pred_filt.dropna(subset=['real_eolica_pct'])
    if not real_data.empty:
        ax3.plot(real_data['fecha'], real_data['real_eolica_pct'], label='Real (% Eólica)', marker='o', color='tab:blue', alpha=0.7)
    # Predicción
    pred_data = pred_filt.dropna(subset=['prediccion_eolica_pct'])
    if not pred_data.empty:
        ax3.plot(pred_data['fecha'], pred_data['prediccion_eolica_pct'], label='Predicción', marker='x', color='tab:orange', linestyle='--', linewidth=2)
    ax3.set_xlabel('Fecha')
    ax3.set_ylabel('% Eólica')
    ax3.grid(True, linestyle='--', alpha=0.6)
    ax3.legend()
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    ax3.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=30)
    plt.tight_layout()
    st.pyplot(fig3)
    
    # Tabla de errores recientes
    st.subheader("Detalle predicciones recientes")
    pred_display = pred_filt.sort_values('fecha', ascending=False).head(14)
    pred_display = pred_display[['fecha', 'prediccion_eolica_pct', 'real_eolica_pct', 'error_pct']].copy()
    pred_display['fecha'] = pred_display['fecha'].dt.strftime('%Y-%m-%d')
    pred_display.columns = ['Fecha', 'Predicción (%)', 'Real (%)', 'Error (p.p.)']
    st.dataframe(pred_display, use_container_width=True, hide_index=True)
else:
    st.info("No hay datos de predicciones disponibles aún. Ejecuta `python src/predecir_eolica_diaria.py` para generar la primera predicción.")

# Footer
st.markdown("---")
st.caption("Datos: REE REData (Canarias, geo_id=8742) + Open-Meteo (4 puntos Canarias). Modelo: Regresión lineal múltiple (viento 4 puntos). Actualización diaria automática (cron 08:15 Atlantic/Canary).")