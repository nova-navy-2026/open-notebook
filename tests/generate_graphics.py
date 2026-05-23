import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import seaborn as sns
import numpy as np
import os

# Colour palette
C_AVG   = '#4C72B0'
C_MIN   = '#55A868'
C_MAX   = '#C44E52'
C_RANGE = '#DD8452'
C_VOL   = '#8172B2'
C_OK    = '#55A868'
C_FAIL  = '#C44E52'

def _label_bars(ax, rects, fmt="{:.2f}s", offset=0.4):
    """Add value labels above each bar."""
    for rect in rects:
        h = rect.get_height()
        if h == 0:
            continue
        ax.annotate(
            fmt.format(h),
            xy=(rect.get_x() + rect.get_width() / 2, h),
            xytext=(0, offset),
            textcoords="offset points",
            ha='center', va='bottom',
            fontsize=7.5, color='#333333',
        )


def generate_report_image(json_path="resultados.json", output_path="load_test_results.png"):
    if not os.path.exists(json_path):
        print(f"Erro: O ficheiro '{json_path}' não foi encontrado.")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    endpoints = data.get("endpoints", [])
    if not endpoints:
        print("Aviso: Não foram encontrados dados de endpoints no JSON.")
        return

    meta      = data["test_metadata"]
    names     = [ep["name"] for ep in endpoints]
    short     = [n.split('/')[-1] if '/' in n else n for n in names]
    avg_times = [ep["avg_time_s"] for ep in endpoints]
    min_times = [ep["min_time_s"] for ep in endpoints]
    max_times = [ep["max_time_s"] for ep in endpoints]
    totals    = [ep["total"]      for ep in endpoints]
    passed_ep = [ep["passed"]     for ep in endpoints]
    failed_ep = [ep["failed"]     for ep in endpoints]

    # Derived metrics
    throughput  = meta["total_requests"] / meta["wall_time_seconds"]   # req/s
    success_pct = 100 * meta["passed"] / meta["total_requests"]

    # ── Layout ──────────────────────────────────────────────────────────────
    sns.set_theme(style="whitegrid", font_scale=0.95)
    fig = plt.figure(figsize=(20, 14))
    fig.patch.set_facecolor('#F7F9FC')

    gs = gridspec.GridSpec(
        3, 3,
        figure=fig,
        hspace=0.55, wspace=0.38,
        left=0.06, right=0.97, top=0.91, bottom=0.07,
    )

    ax_resp   = fig.add_subplot(gs[0, :2])   # row 0, cols 0-1 — response times
    ax_pie    = fig.add_subplot(gs[0, 2])    # row 0, col 2  — success pie
    ax_vol    = fig.add_subplot(gs[1, :2])   # row 1, cols 0-1 — request volume
    ax_range  = fig.add_subplot(gs[1, 2])    # row 1, col 2  — latency range
    ax_table  = fig.add_subplot(gs[2, :])    # row 2, full   — stats table

    fig.suptitle(
        'Load Test Dashboard — Open-Notebook',
        fontsize=18, fontweight='bold', y=0.965, color='#1A1A2E',
    )

    x = np.arange(len(names))
    w = 0.25

    # ── Chart 1: Response times (min / avg / max) ────────────────────────────
    b_min = ax_resp.bar(x - w,     min_times, w, label='Min',   color=C_MIN,   zorder=3)
    b_avg = ax_resp.bar(x,         avg_times, w, label='Avg',   color=C_AVG,   zorder=3)
    b_max = ax_resp.bar(x + w,     max_times, w, label='Max',   color=C_MAX,   zorder=3)
    _label_bars(ax_resp, b_min)
    _label_bars(ax_resp, b_avg)
    _label_bars(ax_resp, b_max)

    ax_resp.set_ylabel('Seconds', fontsize=11)
    ax_resp.set_title('Response Time per Endpoint  (Min / Avg / Max)', fontsize=13, fontweight='bold')
    ax_resp.set_xticks(x)
    ax_resp.set_xticklabels(names, rotation=25, ha='right', fontsize=9)
    ax_resp.legend(fontsize=9)
    ax_resp.set_facecolor('#FFFFFF')

    # ── Chart 2: Server time consumed per endpoint ───────────────────────────
    # consumed_s = total_requests × avg_latency — reveals true capacity cost
    consumed = [t * a for t, a in zip(totals, avg_times)]
    total_consumed = sum(consumed)
    bar_colors = [C_OK if a < 1 else (C_RANGE if a < 15 else C_MAX) for a in avg_times]

    hbars = ax_pie.barh(names[::-1], consumed[::-1],
                        color=bar_colors[::-1], edgecolor='white',
                        linewidth=1.2, zorder=3)
    for bar, val in zip(hbars, consumed[::-1]):
        pct = 100 * val / total_consumed if total_consumed > 0 else 0
        ax_pie.annotate(
            f'{val:.1f}s  ({pct:.1f}%)',
            xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(4, 0), textcoords='offset points',
            va='center', fontsize=8, color='#333333',
        )
    ax_pie.set_xlabel('Total Seconds Consumed', fontsize=10)
    ax_pie.set_title(
        f'Server Time Consumed\n(requests × avg latency  •  total: {total_consumed:.1f}s)',
        fontsize=11, fontweight='bold',
    )
    fast_patch = mpatches.Patch(color=C_OK,    label='< 1 s avg')
    mod_patch  = mpatches.Patch(color=C_RANGE,  label='1–15 s avg')
    slow_patch = mpatches.Patch(color=C_MAX,    label='> 15 s avg')
    ax_pie.legend(handles=[fast_patch, mod_patch, slow_patch],
                  fontsize=7.5, loc='upper right')
    ax_pie.set_facecolor('#FFFFFF')

    # ── Chart 3: Request volume per endpoint ─────────────────────────────────
    b_tot = ax_vol.bar(x - w/2, totals,    w*1.1, label='Total',  color=C_VOL,  zorder=3)
    b_ok  = ax_vol.bar(x + w/2, passed_ep, w*1.1, label='Passed', color=C_OK,   zorder=3, alpha=0.85)
    _label_bars(ax_vol, b_tot, fmt="{:.0f}")
    _label_bars(ax_vol, b_ok,  fmt="{:.0f}")
    if any(f > 0 for f in failed_ep):
        b_fl = ax_vol.bar(x + w/2, failed_ep, w*1.1, label='Failed',
                          color=C_FAIL, zorder=4, bottom=passed_ep, alpha=0.85)
        _label_bars(ax_vol, b_fl, fmt="{:.0f}")
    ax_vol.set_ylabel('Requests', fontsize=11)
    ax_vol.set_title('Request Volume per Endpoint', fontsize=13, fontweight='bold')
    ax_vol.set_xticks(x)
    ax_vol.set_xticklabels(names, rotation=25, ha='right', fontsize=9)
    ax_vol.legend(fontsize=9)
    ax_vol.set_facecolor('#FFFFFF')

    # ── Chart 4: Latency range (error-bar style) ─────────────────────────────
    yerr_low  = [a - mn for a, mn in zip(avg_times, min_times)]
    yerr_high = [mx - a  for a, mx in zip(avg_times, max_times)]
    x_range = list(range(len(short)))
    ax_range.errorbar(
        x_range, avg_times,
        yerr=[yerr_low, yerr_high],
        fmt='o', color=C_AVG, ecolor=C_RANGE,
        elinewidth=2.5, capsize=6, capthick=2,
        markersize=8, zorder=3,
    )
    ax_range.set_ylabel('Seconds', fontsize=11)
    ax_range.set_title('Latency Spread\n(avg ± min/max)', fontsize=11, fontweight='bold')
    ax_range.set_xticks(x_range)
    ax_range.set_xticklabels(short, rotation=30, ha='right', fontsize=8)
    ax_range.set_yscale('symlog', linthresh=1)
    ax_range.yaxis.set_minor_formatter(plt.NullFormatter())
    ax_range.set_facecolor('#FFFFFF')

    # ── Chart 5: Stats table ─────────────────────────────────────────────────
    ax_table.axis('off')

    col_labels = ['Endpoint', 'Requests', 'Passed', 'Failed',
                  'Min (s)', 'Avg (s)', 'Max (s)', 'Spread (s)', 'Pass %']
    table_data = []
    for ep in endpoints:
        spread   = round(ep["max_time_s"] - ep["min_time_s"], 2)
        pass_pct = f'{100 * ep["passed"] / ep["total"]:.1f}%' if ep["total"] > 0 else 'N/A'
        table_data.append([
            ep["name"],
            ep["total"],
            ep["passed"],
            ep["failed"],
            f'{ep["min_time_s"]:.2f}',
            f'{ep["avg_time_s"]:.2f}',
            f'{ep["max_time_s"]:.2f}',
            f'{spread:.2f}',
            pass_pct,
        ])

    # Summary footer row
    total_spread = round(max(ep["max_time_s"] for ep in endpoints)
                         - min(ep["min_time_s"] for ep in endpoints), 2)
    table_data.append([
        'TOTAL / OVERALL',
        meta["total_requests"],
        meta["passed"],
        meta["failed"],
        '—', '—', '—',
        f'{total_spread:.2f}',
        f'{success_pct:.1f}%',
    ])

    tbl = ax_table.table(
        cellText=table_data,
        colLabels=col_labels,
        cellLoc='center',
        loc='center',
        bbox=[0, 0, 1, 1],
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.auto_set_column_width(list(range(len(col_labels))))

    # Header styling
    for j in range(len(col_labels)):
        tbl[0, j].set_facecolor('#1A1A2E')
        tbl[0, j].set_text_props(color='white', fontweight='bold')

    # Row styling: alternating + highlight pass/fail
    for i, ep_row in enumerate(table_data, start=1):
        row_bg = '#EEF2FF' if i % 2 == 0 else '#FFFFFF'
        for j in range(len(col_labels)):
            tbl[i, j].set_facecolor(row_bg)
        # Colour the "Pass %" cell
        pass_cell_text = str(ep_row[-1])
        if pass_cell_text == '100.0%':
            tbl[i, len(col_labels) - 1].set_facecolor('#D4EDDA')
        elif pass_cell_text not in ('N/A', '—'):
            val = float(pass_cell_text.rstrip('%'))
            if val < 90:
                tbl[i, len(col_labels) - 1].set_facecolor('#F8D7DA')
            elif val < 100:
                tbl[i, len(col_labels) - 1].set_facecolor('#FFF3CD')

    # Footer row highlight
    footer_idx = len(table_data)
    for j in range(len(col_labels)):
        tbl[footer_idx, j].set_facecolor('#D0D8F0')
        tbl[footer_idx, j].set_text_props(fontweight='bold')

    ax_table.set_title(
        f'Detailed Endpoint Statistics  •  {meta["concurrent_users"]} concurrent users'
        f'  •  wall time: {meta["wall_time_seconds"]:.1f}s'
        f'  •  throughput: {throughput:.2f} req/s',
        fontsize=11, fontweight='bold', pad=8,
    )

    plt.savefig(output_path, dpi=180, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"[+] Gráfico gerado com sucesso: {output_path}")

if __name__ == "__main__":
    generate_report_image()