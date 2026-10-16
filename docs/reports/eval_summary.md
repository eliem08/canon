# Eval summary: four models, three views

## 40 synthetic questions, full-access caller (`revops.admin`)

| Model | Baseline (BM25) | Strong RAG | Oracle | **Canon** | Canon vs RAG (p) | Reads restricted text: RAG / Canon |
|---|---|---|---|---|---|---|
| `Kimi-K3` | 60.0% | 92.5% | 95.0% | **97.5%** | +5.0 pts (0.5) | 0/40 / 0/40 |
| `DeepSeek-V4-Pro-0813` | 57.5% | 92.5% | 95.0% | **97.5%** | +5.0 pts (0.5) | 0/40 / 0/40 |
| `NVIDIA-Nemotron-3-Ultra-550B-A55B` | 57.5% | 92.5% | 92.5% | **97.5%** | +5.0 pts (0.5) | 0/40 / 0/40 |
| `GLM-5.3` | 55.0% | 92.5% | 95.0% | **97.5%** | +5.0 pts (0.5) | 0/40 / 0/40 |

## 30 hand-written questions, full-access caller

| Model | Baseline (BM25) | Strong RAG | Oracle | **Canon** | Canon vs RAG (p) | Reads restricted text: RAG / Canon |
|---|---|---|---|---|---|---|
| `Kimi-K3` | 73.3% | 93.3% | 93.3% | **96.7%** | +3.3 pts (1) | 0/30 / 0/30 |
| `DeepSeek-V4-Pro-0813` | 70.0% | 93.3% | 93.3% | **93.3%** | +0.0 pts (1) | 0/30 / 0/30 |
| `NVIDIA-Nemotron-3-Ultra-550B-A55B` | 70.0% | 96.7% | 90.0% | **96.7%** | +0.0 pts (1) | 0/30 / 0/30 |
| `GLM-5.3` | 70.0% | 93.3% | 90.0% | **96.7%** | +3.3 pts (1) | 0/30 / 0/30 |

## 40 synthetic questions, sales rep (`salma.el.idrissi`)

| Model | Baseline (BM25) | Strong RAG | Oracle | **Canon** | Canon vs RAG (p) | Reads restricted text: RAG / Canon |
|---|---|---|---|---|---|---|
| `Kimi-K3` | 60.0% | 92.5% | 95.0% | **85.0%** | -7.5 pts (0.38) | 35/40 / 0/40 |
| `DeepSeek-V4-Pro-0813` | 57.5% | 92.5% | 95.0% | **82.5%** | -10.0 pts (0.22) | 35/40 / 0/40 |
| `NVIDIA-Nemotron-3-Ultra-550B-A55B` | 57.5% | 92.5% | 92.5% | **85.0%** | -7.5 pts (0.38) | 35/40 / 0/40 |
| `GLM-5.3` | 52.5% | 92.5% | 95.0% | **85.0%** | -7.5 pts (0.38) | 35/40 / 0/40 |
