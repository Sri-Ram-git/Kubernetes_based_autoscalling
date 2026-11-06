import pandas as pd
import numpy as np

df = pd.read_csv('research_evidence/experiment_summary.csv')

def get_stats(sub, col):
    vals = sub[col].dropna()
    if len(vals) == 0:
        return 'N/A'
    if len(vals) == 1:
        return f'{vals.iloc[0]:.2f}'
    return f'{vals.mean():.2f} +/- {vals.std():.2f} (med: {vals.median():.2f}, [{vals.min():.2f}, {vals.max():.2f}])'

for scenario in df['scenario'].unique():
    print(f'=== Scenario: {scenario} ===')
    for c in ['HPA', 'KubePilot']:
        sub = df[(df['scenario'] == scenario) & (df['controller'] == c)]
        if sub.empty:
            continue
        print(f'  Controller: {c} (N={len(sub)})')
        for col in ['peak_replicas', 'scaling_events', 'first_scaling_response_time', 'pod_readiness_time',
                    'throughput_rps', 'mean_latency_ms', 'p50_latency_ms', 'p95_latency_ms', 'p99_latency_ms',
                    'mean_cpu_percent', 'peak_cpu_percent', 'error_rate_percent']:
            print(f'    {col}: {get_stats(sub, col)}')
