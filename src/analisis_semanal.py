#!/usr/bin/env python3
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Rutas relativas a la raíz del repositorio
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, 'data', 'historico.csv')
METEO_CSV_PATH = os.path.join(BASE_DIR, 'data', 'meteo.csv')
GRAF_DIR = os.path.join(BASE_DIR, 'graficas')

def main():
    if not os.path.exists(CSV_PATH):
        print(f"No se encuentra {CSV_PATH}")
        return

    df = pd.read_csv(CSV_PATH)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df['mwh'] = pd.to_numeric(df['mwh'])
    df['total_mwh'] = pd.to_numeric(df['total_mwh'])
    df['porcentaje_renovable'] = pd.to_numeric(df['porcentaje_renovable'])

    daily = df[['fecha', 'total_mwh', 'porcentaje_renovable']].drop_duplicates(subset=['fecha']).sort_values('fecha').reset_index(drop=True)

    if len(daily) < 14:
        print("No hay suficientes días de datos.")
        return

    # Leer meteo si existe y calcular viento medio diario (promedio de los 4 puntos)
    wind_mean_week = None
    wind_mean_prev_week = None
    if os.path.exists(METEO_CSV_PATH):
        meteo_df = pd.read_csv(METEO_CSV_PATH)
        meteo_df['fecha'] = pd.to_datetime(meteo_df['fecha'])
        meteo_df['viento_medio'] = pd.to_numeric(meteo_df['viento_medio'])
        meteo_daily = meteo_df.groupby('fecha')['viento_medio'].mean().reset_index()
    else:
        meteo_daily = pd.DataFrame(columns=['fecha', 'viento_medio'])

    # Semana natural anterior basada estrictamente en el calendario (lunes a domingo inmediatamente anteriores a hoy)
    today = pd.Timestamp.today().normalize()
    days_since_monday = today.weekday()
    last_sunday = today - pd.Timedelta(days=days_since_monday + 1)
    last_monday = last_sunday - pd.Timedelta(days=6)

    prev_sunday = last_monday - pd.Timedelta(days=1)
    prev_monday = prev_sunday - pd.Timedelta(days=6)

    # Días de la semana natural anterior en el histórico
    week_mask = (daily['fecha'] >= last_monday) & (daily['fecha'] <= last_sunday)
    week_data = daily[week_mask].copy()
    available_days = len(week_data)
    expected_days = 7
    
    missing_days = []
    current = last_monday
    while current <= last_sunday:
        if current not in week_data['fecha'].values:
            missing_days.append(current.strftime('%d/%m'))
        current += pd.Timedelta(days=1)

    # Semana previa a esa (para comparación)
    week2_mask = (daily['fecha'] >= prev_monday) & (daily['fecha'] <= prev_sunday)
    week2_data = daily[week2_mask]

    mean_week = week_data['porcentaje_renovable'].mean() if available_days > 0 else 0
    mean_prev_week = week2_data['porcentaje_renovable'].mean() if len(week2_data) > 0 else 0

    # Viento medio de las dos semanas
    if not meteo_daily.empty:
        w_mask = (meteo_daily['fecha'] >= last_monday) & (meteo_daily['fecha'] <= last_sunday)
        w_prev_mask = (meteo_daily['fecha'] >= prev_monday) & (meteo_daily['fecha'] <= prev_sunday)
        
        w_week_data = meteo_daily[w_mask]
        w_prev_data = meteo_daily[w_prev_mask]
        
        wind_mean_week = w_week_data['viento_medio'].mean() if len(w_week_data) > 0 else None
        wind_mean_prev_week = w_prev_data['viento_medio'].mean() if len(w_prev_data) > 0 else None

    if available_days > 0:
        max_day_row = week_data.loc[week_data['porcentaje_renovable'].idxmax()]
        min_day_row = week_data.loc[week_data['porcentaje_renovable'].idxmin()]

        max_date = max_day_row['fecha']
        min_date = min_day_row['fecha']

        renewable_list = ['Eólica', 'Solar fotovoltaica', 'Hidroeólica', 'Otras renovables']
        
        max_day_techs = df[(df['fecha'] == max_date) & (df['tecnologia'].isin(renewable_list))]
        top_tech_max = max_day_techs.loc[max_day_techs['mwh'].idxmax()]['tecnologia'] if len(max_day_techs) > 0 else "N/D"

        min_day_techs = df[df['fecha'] == min_date]
        top_tech_min = min_day_techs.loc[min_day_techs['mwh'].idxmax()]['tecnologia']
    else:
        max_date = min_date = None
        top_tech_max = top_tech_min = None

    os.makedirs(GRAF_DIR, exist_ok=True)

    # 3. Gráfica 1: Evolución 90 días con media móvil 7d
    df_90 = daily.tail(90).copy()
    df_90['ma_7'] = df_90['porcentaje_renovable'].rolling(window=7).mean()

    plt.figure(figsize=(10, 5))
    plt.plot(df_90['fecha'], df_90['porcentaje_renovable'], label='% Renovable Diario', alpha=0.5, color='tab:green')
    plt.plot(df_90['fecha'], df_90['ma_7'], label='Media Móvil (7 días)', color='darkgreen', linewidth=2)
    plt.title('Evolución Diaria del % Renovable (Últimos 90 días)')
    plt.xlabel('Fecha')
    plt.ylabel('% Renovable')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gca().xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=30)
    plt.tight_layout()
    chart1_path = os.path.join(GRAF_DIR, 'evolucion_renovable_90d.png')
    plt.savefig(chart1_path, dpi=300)
    plt.close()

    # 4. Gráfica 2: Barras apiladas mix tecnológico 4 semanas naturales (lunes a domingo)
    week_labels = []
    df_28 = df.copy()
    
    for w in range(4):
        w_sunday = last_sunday - pd.Timedelta(weeks=w)
        w_monday = w_sunday - pd.Timedelta(days=6)
        label = f"{w_monday.strftime('%d/%m')} - {w_sunday.strftime('%d/%m')}"
        week_labels.append(label)
        mask = (df_28['fecha'] >= w_monday) & (df_28['fecha'] <= w_sunday)
        df_28.loc[mask, 'semana_label'] = label

    week_labels = list(reversed(week_labels))

    pivot_mix = df_28.pivot_table(index='semana_label', columns='tecnologia', values='mwh', aggfunc='sum')
    pivot_mix = pivot_mix.reindex(week_labels)
    pivot_mix_pct = pivot_mix.div(pivot_mix.sum(axis=1), axis=0) * 100

    fossil_techs = [t for t in pivot_mix_pct.columns if t in ['Ciclo combinado', 'Motores diésel', 'Turbina de vapor', 'Turbina de gas']]
    renewable_techs = [t for t in pivot_mix_pct.columns if t not in fossil_techs]
    ordered_techs = fossil_techs + renewable_techs
    pivot_mix_pct = pivot_mix_pct[ordered_techs]

    color_map = {
        'Ciclo combinado': '#4d4d4d',
        'Motores diésel': '#8c6239',
        'Turbina de vapor': '#7f7f7f',
        'Turbina de gas': '#b58958',
        'Otras renovables': '#c7e9c0',
        'Hidroeólica': '#74c476',
        'Solar fotovoltaica': '#ffeda0',
        'Eólica': '#238b45'
    }
    bar_colors = [color_map.get(t, '#cccccc') for t in ordered_techs]

    plt.figure(figsize=(10, 5))
    ax = pivot_mix_pct.plot(kind='bar', stacked=True, figsize=(10, 5), color=bar_colors)
    plt.title('Mix Tecnológico de Generación (Últimas 4 Semanas Naturales en %)')
    plt.xlabel('Semana (Lun - Dom)')
    plt.ylabel('Porcentaje de Generación (%)')
    plt.xticks(rotation=15)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    plt.tight_layout()
    chart2_path = os.path.join(GRAF_DIR, 'mix_tecnologia_4sem.png')
    plt.savefig(chart2_path, dpi=300)
    plt.close()

    # Imprimir resumen de prueba (sin MEDIA:)
    missing_str = f"; faltan {', '.join(missing_days)}" if missing_days else ""
    print(f"Semana analizada: {last_monday.strftime('%d/%m/%Y')} al {last_sunday.strftime('%d/%m/%Y')}")
    print(f"Datos disponibles: {available_days} de {expected_days} días{missing_str}.")
    print(f"1. % renovable medio = {mean_week:.2f}% (vs {mean_prev_week:.2f}% semana anterior).")
    if wind_mean_week is not None and wind_mean_prev_week is not None:
        diff_wind = wind_mean_week - wind_mean_prev_week
        sign_w = "+" if diff_wind >= 0 else ""
        print(f"   Viento medio semanal = {wind_mean_week:.2f} m/s (vs {wind_mean_prev_week:.2f} m/s anterior, {sign_w}{diff_wind:.2f} m/s).")
    if max_date is not None:
        print(f"2. Día más renovable: {max_date.strftime('%d/%m')} ({max_day_row['porcentaje_renovable']:.2f}%), destacando {top_tech_max}.")
        print(f"3. Día menos renovable: {min_date.strftime('%d/%m')} ({min_day_row['porcentaje_renovable']:.2f}%), destacando {top_tech_min}.")
    else:
        print("2. Día más renovable: N/D")
        print("3. Día menos renovable: N/D")

if __name__ == '__main__':
    main()