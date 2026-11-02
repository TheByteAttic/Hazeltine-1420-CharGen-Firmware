# Copyright (c) 2026 by The Byte Attic B.V.
"""Render layout_<v>.json to PNG (view from the top; bottom copper seen through the board)."""
import json, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Polygon

def render(fn, out, dpi=220):
    d = json.load(open(fn))
    poly = d['outline']
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    W, H = max(xs) - min(xs), max(ys) - min(ys)
    fig, ax = plt.subplots(figsize=(W / 6, H / 6))
    ax.add_patch(Polygon(poly, closed=True, fill=False, lw=1.5, ec='k'))
    col = {'top': '#c0392b', 'bot': '#2471a3'}
    for L in ('bot', 'top'):
        for t in d['tracks']:
            if t['layer'] != L: continue
            px, py = zip(*t['pts'])
            ax.plot(px, py, color=col[L], lw=t['w'] * 6.5, solid_capstyle='round', solid_joinstyle='round',
                    alpha=0.85, zorder=2 if L == 'top' else 1)
    for layer, pr in d.get('pours', {}).items():
        c = '#aed6f1' if layer == 'bot' else '#f5b7b1'
        for poly in pr.get('outers', []):
            ax.add_patch(Polygon(poly, closed=True, fc=c, ec='none', zorder=0.5))
        for poly in pr.get('holes', []):
            ax.add_patch(Polygon(poly, closed=True, fc='w', ec='none', zorder=0.6))
    for td in d.get('teardrops', []):
        ax.add_patch(Polygon(td['pts'], closed=True, fc=col[td['layer']], ec='none', alpha=0.85, zorder=2 if td['layer'] == 'top' else 1))
    for v in d['vias']:
        ax.add_patch(Circle((v['x'], v['y']), 0.35, fc='#7d3c98', ec='k', lw=0.3, zorder=3))
    for p in d['pads']:
        if p['shape'] == 'smd':
            w, h = p['size']
            fc = '#d4ac0d' if 'top' in p['layers'] else '#85c1e9'
            ax.add_patch(Rectangle((p['x'] - w / 2, p['y'] - h / 2), w, h, fc=fc, ec='k', lw=0.3, zorder=3))
        else:
            s = p['size']
            if p['shape'] == 'rect':
                ax.add_patch(Rectangle((p['x'] - s / 2, p['y'] - s / 2), s, s, fc='#d4ac0d', ec='k', lw=0.3, zorder=3))
            else:
                ax.add_patch(Circle((p['x'], p['y']), s / 2, fc='#d4ac0d', ec='k', lw=0.3, zorder=3))
            ax.add_patch(Circle((p['x'], p['y']), p['hole'] / 2, fc='w', ec='none', zorder=4))
    # reference labels at pad centroids
    refs = {}
    for p in d['pads']:
        refs.setdefault(p['ref'], []).append((p['x'], p['y']))
    for ref, pts in refs.items():
        cx = sum(x for x, _ in pts) / len(pts); cy = sum(y for _, y in pts) / len(pts)
        ax.text(cx, cy, ref, ha='center', va='center', fontsize=7, zorder=6, color='#222')
    ax.set_xlim(min(xs) - 1, max(xs) + 1); ax.set_ylim(min(ys) - 1, max(ys) + 1)
    ax.set_aspect('equal'); ax.axis('off')
    fig.savefig(out, dpi=dpi, bbox_inches='tight')
    print('wrote', out)

if __name__ == '__main__':
    v = sys.argv[1] if len(sys.argv) > 1 else 'U'
    render(f'layout_{v}.json', f'preview_{v}.png')
