import json
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import os

def generate_report_image(json_path="resultados.json", output_path="load_test_results.png"):
    if not os.path.exists(json_path):
        print(f"Erro: O ficheiro '{json_path}' não foi encontrado.")
        return

    # Carregar os dados gerados pelo teste de carga
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    endpoints = data.get("endpoints", [])
    if not endpoints:
        print("Aviso: Não foram encontrados dados de endpoints no JSON.")
        return

    names = [ep["name"] for ep in endpoints]
    avg_times = [ep["avg_time_s"] for ep in endpoints]
    max_times = [ep["max_time_s"] for ep in endpoints]
    
    # Configurar estilo visual profissional
    sns.set_theme(style="whitegrid")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    fig.suptitle('Resultados do Teste de Carga - Open-Notebook', fontsize=18, fontweight='bold', y=1.05)

    # Gráfico 1: Tempos de Resposta (Médio vs Máximo)
    x = np.arange(len(names))
    width = 0.35

    ax1.bar(x - width/2, avg_times, width, label='Tempo Médio (s)', color='#4C72B0')
    ax1.bar(x + width/2, max_times, width, label='Tempo Máximo (s)', color='#C44E52')

    ax1.set_ylabel('Segundos', fontsize=12)
    ax1.set_title('Tempos de Resposta por Endpoint', fontsize=14)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=45, ha='right')
    ax1.legend()

    # Gráfico 2: Taxa de Sucesso vs Falha Geral
    meta = data["test_metadata"]
    labels = ['Sucesso', 'Falha']
    sizes = [meta["passed"], meta["failed"]]
    colors = ['#55A868', '#C44E52']
    
    # Se houver 0 falhas, ajustamos para não quebrar o gráfico
    if meta["failed"] > 0:
        explode = (0, 0.1)
    else:
        explode = (0,)
        labels = ['Sucesso']
        sizes = [meta["passed"]]
        colors = ['#55A868']

    ax2.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%',
            shadow=True, startangle=90, textprops={'fontsize': 12})
    ax2.axis('equal')
    ax2.set_title(f'Fiabilidade Global\n(Total de Pedidos: {meta["total_requests"]})', fontsize=14)

    # Ajustar layout e guardar imagem
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[+] Gráfico gerado com sucesso: {output_path}")

if __name__ == "__main__":
    generate_report_image()