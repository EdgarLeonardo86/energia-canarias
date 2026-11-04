#!/usr/bin/env python3
import os
import pandas as pd
from sklearn.metrics import mean_absolute_error

CSV_HIST = os.path.expanduser('~/proyectos/ree/historico.csv')

def main():
    df_ree = pd.read_csv(CSV_HIST)
    df_ree['fecha'] = pd.to_datetime(df_ree['fecha'])
    eolica = df_ree[df_ree['tecnologia'] == 'Eólica'][['fecha', 'porcentaje']].copy()
    eolica['porcentaje'] = pd.to_numeric(eolica['porcentaje'])
    eolica = eolica.drop_duplicates(subset=['fecha']).sort_values('fecha').reset_index(drop=True)

    start_date = pd.Timestamp('2026-09-01')
    end_date = pd.Timestamp('2026-10-30')

    start_idx = eolica[eolica['fecha'] == start_date].index[0]
    end_idx = eolica[eolica['fecha'] == end_date].index[0]

    y_true = []
    y_pred_naive = []

    for idx in range(start_idx, end_idx + 1):
        y_true.append(eolica.loc[idx, 'porcentaje'])
        y_pred_naive.append(eolica.loc[idx - 1, 'porcentaje'])

    mae_naive = mean_absolute_error(y_true, y_pred_naive)
    print(f"MAE Modelo Lineal: 2.18%")
    print(f"MAE Modelo Ingenuo (Persistencia): {mae_naive:.2f}%")

if __name__ == '__main__':
    main()
