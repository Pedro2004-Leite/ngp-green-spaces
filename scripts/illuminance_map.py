#!/usr/bin/env python3
"""
Gera um mapa de iluminância a partir de uma mesh exportada pelo Instant-NGP.

A luminância da textura serve como proxy para a iluminância relativa do espaço.
Com pontos de referência medidos (luxímetro), o mapa é calibrado para lux reais.

Dependências:
    pip install trimesh pillow matplotlib numpy scipy

Uso:
    # Mapa de luminância relativa (sem calibração)
    python scripts/illuminance_map.py --mesh dataset/mesh.obj

    # Mapa calibrado em lux (com medições de referência)
    python scripts/illuminance_map.py --mesh dataset/mesh.obj --lux_refs refs.csv

    # Controlar resolução e saída
    python scripts/illuminance_map.py --mesh dataset/mesh.obj --resolution 1024 --output resultado.png
"""

import argparse
import os
import sys
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


# ---------------------------------------------------------------------------
# Conversão de cor
# ---------------------------------------------------------------------------

def rgb_to_luminance(rgb):
    """Converte RGB [0–255] para luminância perceptual (ITU-R BT.709)."""
    r = rgb[..., 0].astype(np.float32) / 255.0
    g = rgb[..., 1].astype(np.float32) / 255.0
    b = rgb[..., 2].astype(np.float32) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# Projeção top-down por ray casting
# ---------------------------------------------------------------------------

def render_top_down(mesh, texture_image, resolution):
    """
    Projeta a mesh ortogonalmente de cima para baixo e amostra a textura
    em cada ponto de interseção. Retorna (luminance_map, hit_mask).

    luminance_map : ndarray (H, W) float32, valores em [0, 1]
    hit_mask      : ndarray (H, W) bool, True onde existe geometria
    """
    import trimesh

    bounds = mesh.bounds  # [[x_min, y_min, z_min], [x_max, y_max, z_max]]
    x_min, y_min = bounds[0][0], bounds[0][1]
    x_max, y_max = bounds[1][0], bounds[1][1]
    z_top = bounds[1][2] + 0.5  # raios começam acima da mesh

    # Grid de origens (correspondência pixel ↔ posição XY no espaço)
    xs = np.linspace(x_min, x_max, resolution)
    ys = np.linspace(y_min, y_max, resolution)
    xx, yy = np.meshgrid(xs, ys)

    ray_origins = np.stack(
        [xx.ravel(), yy.ravel(), np.full(xx.size, z_top)], axis=1
    )
    ray_directions = np.tile([0.0, 0.0, -1.0], (ray_origins.shape[0], 1))

    print(f"  A lançar {ray_origins.shape[0]:,} raios...")
    locations, index_ray, index_tri = mesh.ray.intersects_location(
        ray_origins=ray_origins,
        ray_directions=ray_directions,
        multiple_hits=False,
    )

    luminance_map = np.zeros(resolution * resolution, dtype=np.float32)
    hit_mask = np.zeros(resolution * resolution, dtype=bool)

    if len(locations) == 0:
        print("  Aviso: nenhum raio atingiu a mesh. Verifica se a mesh tem geometria.")
        return luminance_map.reshape(resolution, resolution), hit_mask.reshape(resolution, resolution)

    hit_mask[index_ray] = True
    print(f"  Raios com hit: {hit_mask.sum():,} / {hit_mask.size:,} ({100*hit_mask.mean():.1f}%)")

    tex_array = np.array(texture_image.convert("RGB"))
    tex_h, tex_w = tex_array.shape[:2]

    # --- Interpolação baricêntrica de UVs ---
    has_uv = (
        hasattr(mesh.visual, "kind")
        and mesh.visual.kind == "texture"
        and mesh.visual.uv is not None
    )

    if has_uv:
        import trimesh.triangles as tri_utils
        bary = tri_utils.points_to_barycentric(
            triangles=mesh.triangles[index_tri],
            points=locations,
        )
        uv_per_vert = mesh.visual.uv          # (N_verts, 2)
        face_uvs = uv_per_vert[mesh.faces[index_tri]]  # (N_hits, 3, 2)
        hit_uvs = np.einsum("ij,ijk->ik", bary, face_uvs)

        u = np.clip(hit_uvs[:, 0], 0.0, 1.0)
        v = np.clip(1.0 - hit_uvs[:, 1], 0.0, 1.0)  # flip V (OBJ: origem bottom-left)
        px = (u * (tex_w - 1)).astype(int)
        py = (v * (tex_h - 1)).astype(int)

        colors = tex_array[py, px]
        luminance_map[index_ray] = rgb_to_luminance(colors)

    # --- Fallback: cores por vértice ---
    elif hasattr(mesh.visual, "vertex_colors") and mesh.visual.vertex_colors is not None:
        import trimesh.triangles as tri_utils
        bary = tri_utils.points_to_barycentric(
            triangles=mesh.triangles[index_tri],
            points=locations,
        )
        vc = mesh.visual.vertex_colors[:, :3].astype(np.float32)
        face_vc = vc[mesh.faces[index_tri]]  # (N_hits, 3, 3)
        hit_colors = np.einsum("ij,ijk->ik", bary, face_vc)
        luminance_map[index_ray] = rgb_to_luminance(hit_colors)

    else:
        print("  Aviso: mesh sem UVs nem cores por vértice. O mapa mostra apenas cobertura.")
        luminance_map[index_ray] = 1.0

    return (
        luminance_map.reshape(resolution, resolution),
        hit_mask.reshape(resolution, resolution),
    )


# ---------------------------------------------------------------------------
# Calibração lux
# ---------------------------------------------------------------------------

def calibrate_to_lux(luminance_map, hit_mask, lux_refs_path):
    """
    Ajusta uma regressão linear entre luminância [0–1] e lux medidos.

    O CSV deve ter cabeçalho: x,y,lux
    x, y são coordenadas normalizadas [0–1] no mapa (origem: canto superior esquerdo).
    """
    import csv

    refs = []
    with open(lux_refs_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            refs.append((float(row["x"]), float(row["y"]), float(row["lux"])))

    if len(refs) < 2:
        raise ValueError("São necessários pelo menos 2 pontos de referência para calibração.")

    h, w = luminance_map.shape
    lum_vals, lux_vals = [], []

    for nx, ny, lux in refs:
        px = int(np.clip(nx * (w - 1), 0, w - 1))
        py = int(np.clip(ny * (h - 1), 0, h - 1))
        lum_vals.append(luminance_map[py, px])
        lux_vals.append(lux)

    lum_vals = np.array(lum_vals)
    lux_vals = np.array(lux_vals)

    a, b = np.polyfit(lum_vals, lux_vals, 1)
    r2 = np.corrcoef(lum_vals, lux_vals)[0, 1] ** 2
    print(f"  Calibração: lux = {a:.1f} × luminância + {b:.1f}  (R² = {r2:.3f})")
    if r2 < 0.7:
        print("  Aviso: R² baixo — os pontos de referência podem ser insuficientes ou inconsistentes.")

    lux_map = np.where(hit_mask, np.clip(a * luminance_map + b, 0.0, None), np.nan)
    return lux_map


# ---------------------------------------------------------------------------
# Visualização
# ---------------------------------------------------------------------------

PLANT_ZONES = [
    (0,    50,   "#111111", "Sem luz (<50 lux)"),
    (50,   250,  "#4a7c59", "Baixa (50–250 lux)\nSansevieria, Zamioculcas"),
    (250,  1000, "#f9c74f", "Média (250–1000 lux)\nFicus, Dracena, Pothos"),
    (1000, None, "#e63946", "Alta (>1000 lux)\nSuculentas, ervas aromáticas"),
]


def save_heatmap(data, hit_mask, output_path, title, cbar_label, colormap="YlOrRd"):
    """Guarda mapa de calor contínuo com colorbar."""
    display = np.where(hit_mask, data, np.nan)

    fig, ax = plt.subplots(figsize=(10, 10))
    img = ax.imshow(display, origin="upper", cmap=colormap, interpolation="bilinear")
    cbar = fig.colorbar(img, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(cbar_label, fontsize=12)
    ax.set_title(title, fontsize=14, pad=12)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path}")


def save_plant_zones(lux_map, hit_mask, output_path):
    """Guarda mapa discreto por zona de aptidão para plantas."""
    h, w = lux_map.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    patches = []

    for lo, hi, hex_col, label in PLANT_ZONES:
        color_rgb = (np.array(mcolors.to_rgb(hex_col)) * 255).astype(np.uint8)
        cond = (lux_map >= lo) & ((lux_map < hi) if hi is not None else True)
        mask = hit_mask & cond
        rgb[mask] = color_rgb
        patches.append(plt.Rectangle((0, 0), 1, 1, color=hex_col, label=label))

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.imshow(rgb, origin="upper")
    ax.legend(
        handles=patches,
        loc="lower right",
        fontsize=9,
        framealpha=0.85,
        title="Aptidão para plantas",
        title_fontsize=10,
    )
    ax.set_title("Zonas de Aptidão para Plantas — Vista Top-Down", fontsize=14, pad=12)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Guardado: {output_path}")


def print_zone_stats(lux_map, hit_mask):
    """Imprime estatísticas por zona."""
    valid = lux_map[hit_mask & ~np.isnan(lux_map)]
    if len(valid) == 0:
        return
    print("\n  Distribuição por zona:")
    for lo, hi, _, label in PLANT_ZONES:
        n = np.sum((valid >= lo) & ((valid < hi) if hi is not None else True))
        pct = 100.0 * n / len(valid)
        name = label.split("\n")[0]
        print(f"    {name:30s}  {pct:5.1f}%  ({n:,} px)")
    print(f"  Lux: min={valid.min():.0f}  max={valid.max():.0f}  média={valid.mean():.0f}")


# ---------------------------------------------------------------------------
# Deteção automática de textura
# ---------------------------------------------------------------------------

def find_texture(obj_path):
    base = os.path.splitext(obj_path)[0]
    folder = os.path.dirname(obj_path)
    candidates = []

    for ext in (".png", ".jpg", ".jpeg"):
        candidates.append(base + ext)
        for name in ("texture", "albedo", "diffuse", "color"):
            candidates.append(os.path.join(folder, name + ext))

    for p in candidates:
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Gera mapa de iluminância top-down a partir de mesh NeRF."
    )
    parser.add_argument("--mesh", required=True, help="Ficheiro .obj exportado pelo Instant-NGP")
    parser.add_argument("--texture", help="Textura da mesh (deteta automaticamente se omitido)")
    parser.add_argument("--output", default="illuminance_map.png", help="Imagem de saída principal")
    parser.add_argument("--resolution", type=int, default=512, help="Resolução do mapa em píxeis (default: 512)")
    parser.add_argument("--lux_refs", help="CSV de calibração com colunas: x,y,lux")
    parser.add_argument("--colormap", default="YlOrRd", help="Colormap matplotlib (default: YlOrRd)")
    args = parser.parse_args()

    try:
        import trimesh
    except ImportError:
        print("Erro: trimesh não instalado.\n  pip install trimesh")
        sys.exit(1)

    # --- Carregar mesh ---
    print(f"\nA carregar mesh: {args.mesh}")
    scene_or_mesh = trimesh.load(args.mesh, force="mesh", process=False)

    if isinstance(scene_or_mesh, trimesh.Scene):
        geometries = list(scene_or_mesh.geometry.values())
        if not geometries:
            print("Erro: a cena não contém geometria.")
            sys.exit(1)
        mesh = trimesh.util.concatenate(geometries)
    else:
        mesh = scene_or_mesh

    print(f"  Vértices : {len(mesh.vertices):,}")
    print(f"  Faces    : {len(mesh.faces):,}")
    print(f"  Bounds   : {mesh.bounds.tolist()}")

    # --- Carregar textura ---
    texture_path = args.texture or find_texture(args.mesh)
    if texture_path:
        print(f"  Textura  : {texture_path}")
        texture_image = Image.open(texture_path).convert("RGB")
    else:
        print("  Textura  : não encontrada — mapa mostrará apenas cobertura geométrica.")
        texture_image = Image.new("RGB", (4, 4), (255, 255, 255))

    # --- Ray casting top-down ---
    print(f"\nA gerar mapa top-down ({args.resolution}×{args.resolution} px)...")
    luminance_map, hit_mask = render_top_down(mesh, texture_image, args.resolution)

    stem = os.path.splitext(args.output)[0]

    # --- Sem calibração: mapa de luminância relativa ---
    if not args.lux_refs:
        print("\nA guardar mapa de luminância relativa...")
        save_heatmap(
            luminance_map, hit_mask, args.output,
            title="Mapa de Luminância Relativa — Vista Top-Down",
            cbar_label="Luminância relativa [0–1]",
            colormap=args.colormap,
        )
        print("\nNota: para um mapa em lux, fornece --lux_refs com medições de um luxímetro.")
        print("      Exemplo: python scripts/illuminance_map.py --mesh mesh.obj --lux_refs scripts/lux_refs_example.csv")

    # --- Com calibração: mapa em lux + zonas de plantas ---
    else:
        try:
            from scipy.stats import pearsonr  # noqa: F401 (apenas para verificar que scipy existe)
        except ImportError:
            print("Aviso: scipy não instalado — a calibração usa numpy.\n  pip install scipy")

        print(f"\nA calibrar com: {args.lux_refs}")
        lux_map = calibrate_to_lux(luminance_map, hit_mask, args.lux_refs)
        print_zone_stats(lux_map, hit_mask)

        print("\nA guardar mapas...")
        save_heatmap(
            lux_map, hit_mask, args.output,
            title="Mapa de Iluminância — Vista Top-Down",
            cbar_label="Iluminância [lux]",
            colormap=args.colormap,
        )
        plants_path = stem + "_plantas.png"
        save_plant_zones(lux_map, hit_mask, plants_path)

    print("\nConcluído.")


if __name__ == "__main__":
    main()
