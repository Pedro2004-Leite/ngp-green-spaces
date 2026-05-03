"""
Simula iluminância física num espaço interior e exporta mapa top-down.

Corre dentro do Blender via linha de comandos:

    blender --background --python scripts/blender_illuminance.py -- ^
        --mesh dataset/mesh.obj ^
        --output illuminance_blender.png ^
        --resolution 1024

Ou interativamente: abrir o Blender, ir ao Scripting tab, colar e correr.

O script:
  1. Importa a mesh do Instant-NGP
  2. Adiciona câmara ortogonal apontada para baixo (vista top-down)
  3. Adiciona luz de área (sky) calibrável
  4. Renderiza com Cycles em formato EXR (HDR)
  5. Processa o EXR para gerar mapa de luminância e heatmap de plantas

Dependências: Blender 3.x ou superior (inclui Python + bpy).
Para processar o EXR final também é necessário: pip install numpy pillow matplotlib
(no Python do sistema, não do Blender)
"""

import sys
import os
import argparse


# ---------------------------------------------------------------------------
# Argumentos — o Blender passa os args do script após "--"
# ---------------------------------------------------------------------------

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh", required=True, help="Ficheiro .obj da mesh")
    parser.add_argument("--output", default="illuminance_blender.png", help="Imagem de saída")
    parser.add_argument("--resolution", type=int, default=1024, help="Resolução de render")
    parser.add_argument("--sun_strength", type=float, default=5.0,
                        help="Intensidade da luz solar (W/m²·sr). Default: 5.0")
    parser.add_argument("--add_sky", action="store_true", default=True,
                        help="Adicionar céu HDRI como iluminação ambiente")
    parser.add_argument("--samples", type=int, default=128,
                        help="Amostras Cycles (mais = menos ruído, mais lento). Default: 128")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Setup da cena Blender
# ---------------------------------------------------------------------------

def setup_scene(args):
    import bpy
    import mathutils

    # Limpar cena default
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    # --- Importar mesh ---
    print(f"A importar mesh: {args.mesh}")
    bpy.ops.import_scene.obj(filepath=os.path.abspath(args.mesh))
    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("Nenhuma mesh foi importada. Verifica o caminho do ficheiro.")

    # Centrar na origem e calcular bounds para posicionar câmara
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")

    all_verts = []
    for obj in mesh_objects:
        for v in obj.data.vertices:
            all_verts.append(obj.matrix_world @ v.co)

    xs = [v.x for v in all_verts]
    ys = [v.y for v in all_verts]
    zs = [v.z for v in all_verts]
    z_max = max(zs)
    cam_z = z_max + max(max(xs) - min(xs), max(ys) - min(ys))  # altitude da câmara
    scene_center_x = (max(xs) + min(xs)) / 2
    scene_center_y = (max(ys) + min(ys)) / 2
    ortho_scale = max(max(xs) - min(xs), max(ys) - min(ys)) * 1.05

    # --- Câmara ortogonal top-down ---
    cam_data = bpy.data.cameras.new("CamTopDown")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_end = cam_z + 10.0

    cam_obj = bpy.data.objects.new("CamTopDown", cam_data)
    cam_obj.location = mathutils.Vector((scene_center_x, scene_center_y, cam_z))
    cam_obj.rotation_euler = mathutils.Euler((0.0, 0.0, 0.0))  # aponta para -Z
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    print(f"  Câmara posicionada em Z={cam_z:.2f}, ortho_scale={ortho_scale:.2f}")

    # --- Iluminação ---
    # Luz solar direcional (simula janelas / luz exterior)
    sun_data = bpy.data.lights.new("Sun", type="SUN")
    sun_data.energy = args.sun_strength
    sun_data.angle = 0.009   # sol com disco angular real (~0.53°)
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    sun_obj.location = (scene_center_x, scene_center_y, cam_z)
    sun_obj.rotation_euler = mathutils.Euler((0.2, 0.1, 0.0))  # ligeiro ângulo
    bpy.context.collection.objects.link(sun_obj)

    # Sky texture como iluminação ambiente
    if args.add_sky:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
        world.use_nodes = True
        nodes = world.node_tree.nodes
        links = world.node_tree.links
        nodes.clear()

        bg = nodes.new("ShaderNodeBackground")
        sky = nodes.new("ShaderNodeTexSky")
        sky.sky_type = "NISHITA"
        sky.sun_elevation = 0.5   # ~30° acima do horizonte
        output = nodes.new("ShaderNodeOutputWorld")

        links.new(sky.outputs["Color"], bg.inputs["Color"])
        links.new(bg.outputs["Background"], output.inputs["Surface"])
        bg.inputs["Strength"].default_value = 1.0

    # --- Render settings ---
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"  # HDR float
    scene.render.image_settings.color_mode = "RGB"

    # Usar render pass de iluminância direta (Combined = radiância total)
    scene.view_layers["ViewLayer"].use_pass_combined = True
    scene.view_layers["ViewLayer"].use_pass_diffuse_direct = True

    return scene


# ---------------------------------------------------------------------------
# Render e pós-processamento
# ---------------------------------------------------------------------------

def render_and_process(args, scene):
    import bpy

    exr_path = os.path.splitext(os.path.abspath(args.output))[0] + ".exr"
    scene.render.filepath = exr_path

    print(f"\nA renderizar ({args.resolution}×{args.resolution}, {args.samples} samples)...")
    bpy.ops.render.render(write_still=True)
    print(f"  EXR guardado: {exr_path}")

    process_exr(exr_path, args.output)


def process_exr(exr_path, output_path):
    """Converte o EXR renderizado num heatmap de iluminância."""
    try:
        import numpy as np
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        print("Aviso: numpy/matplotlib não disponíveis no Python do Blender.")
        print(f"  EXR raw disponível em: {exr_path}")
        print("  Para converter, corre externamente:")
        print(f"    python scripts/process_exr.py --exr {exr_path} --output {output_path}")
        return

    # Blender guarda EXR com OpenEXR — usar imageio ou Pillow com plugin
    try:
        import imageio
        exr_data = imageio.imread(exr_path, format="EXR-FI")
    except Exception:
        try:
            # Fallback: usar bpy para ler o EXR (dentro do Blender)
            import bpy
            img = bpy.data.images.load(exr_path)
            w, h = img.size
            pixels = np.array(img.pixels[:]).reshape(h, w, 4)
            exr_data = pixels[::-1, :, :3]  # flip vertical, sem alpha
        except Exception as e:
            print(f"Não foi possível ler o EXR: {e}")
            print(f"  Usa 'python scripts/process_exr.py --exr {exr_path}' externamente.")
            return

    # Luminância perceptual a partir dos canais RGB HDR
    luminance = (
        0.2126 * exr_data[..., 0]
        + 0.7152 * exr_data[..., 1]
        + 0.0722 * exr_data[..., 2]
    )

    # Guardar heatmap
    fig, axes = plt.subplots(1, 2, figsize=(18, 8))

    # --- Mapa contínuo ---
    im = axes[0].imshow(luminance, origin="upper", cmap="YlOrRd")
    fig.colorbar(im, ax=axes[0], label="Luminância relativa (HDR)")
    axes[0].set_title("Luminância — Render Físico (Cycles)", fontsize=13)
    axes[0].axis("off")

    # --- Mapa por zonas de plantas (em unidades relativas) ---
    p25, p75 = np.percentile(luminance[luminance > 0], [25, 75])
    zones_rgb = np.zeros((*luminance.shape, 3), dtype=np.uint8)
    zone_defs = [
        (0,    p25 * 0.5,  "#111111", "Sem luz"),
        (p25 * 0.5, p25,   "#4a7c59", "Baixa luminosidade"),
        (p25,  p75,        "#f9c74f", "Luminosidade média"),
        (p75,  np.inf,     "#e63946", "Alta luminosidade"),
    ]
    patches = []
    for lo, hi, hex_col, label in zone_defs:
        color = (np.array(mcolors.to_rgb(hex_col)) * 255).astype(np.uint8)
        mask = (luminance >= lo) & (luminance < hi)
        zones_rgb[mask] = color
        patches.append(plt.Rectangle((0, 0), 1, 1, color=hex_col, label=label))

    axes[1].imshow(zones_rgb, origin="upper")
    axes[1].legend(handles=patches, loc="lower right", fontsize=9,
                   title="Aptidão para plantas", framealpha=0.85)
    axes[1].set_title("Zonas de Aptidão para Plantas", fontsize=13)
    axes[1].axis("off")

    plt.suptitle("Mapa de Iluminância — Vista Top-Down (Simulação Física)", fontsize=15, y=1.01)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Heatmap guardado: {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = parse_args()

    try:
        import bpy
    except ImportError:
        print("Erro: este script deve ser executado dentro do Blender.")
        print("  blender --background --python scripts/blender_illuminance.py -- --mesh mesh.obj")
        sys.exit(1)

    scene = setup_scene(args)
    render_and_process(args, scene)
    print("\nConcluído.")


if __name__ == "__main__":
    main()
