#!/usr/bin/env python3
"""
patch_and_compile_spirv.py
==========================
Converte shaders GLSL OpenGL (#version 150) dos preprocessed/ do Minecraft
para Vulkan GLSL (#version 450) e compila com glslc para SPIR-V.

Transformações aplicadas:
  - #version 150 → #version 450
  - `in TYPE NAME;` → `layout(location=N) in TYPE NAME;`
  - `out TYPE NAME;` → `layout(location=N) out TYPE NAME;`
  - `uniform samplerXX NAME;` → `layout(binding=N) uniform samplerXX NAME;`
  - `uniform TYPE NAME;` (matrizes, vec, float…) → agrupados num UBO anónimo
    `layout(std140, binding=0) uniform VKBlock { ... };`
  - `gl_FragColor` → `layout(location=0) out vec4 fragColor; + replace`

Uso (a partir da raiz do repositório):
  python3 patch_and_compile_spirv.py

Requisito: glslc no PATH.
"""

import os
import re
import sys
import struct
import shutil
import subprocess
import tempfile

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
REPO_ROOT        = os.getcwd()
PREPROCESSED_DIR = "/tmp/vulkanmod_build_final/preprocessed"
OUTPUT_BASE      = os.path.join(REPO_ROOT,
                   "src/main/resources/assets/vulkanmod/shaders/basic")
SPIRV_MAGIC      = 0x07230203

# ---------------------------------------------------------------------------
# Tipos que são samplers (opaque) — ficam fora do UBO
# ---------------------------------------------------------------------------
SAMPLER_TYPES = re.compile(
    r'\b(?:sampler\w*|image\w*|atomic_uint)\b'
)

# ---------------------------------------------------------------------------
# Mapeamento pipeline → (nome_fonte_vsh, nome_fonte_fsh)
# ---------------------------------------------------------------------------
PIPELINE_MAP = {
    "gui":                              ("rendertype_gui",                        "rendertype_gui"),
    "gui_textured":                     ("rendertype_gui",                        "rendertype_gui"),
    "gui_text":                         ("rendertype_gui",                        "rendertype_gui"),
    "gui_text_highlight":               ("rendertype_gui_text_highlight",         "rendertype_gui_text_highlight"),
    "gui_invert":                       ("rendertype_gui_overlay",                "rendertype_gui_overlay"),
    "gui_nausea_overlay":               ("rendertype_gui_overlay",                "rendertype_gui_overlay"),
    "gui_opaque_textured_background":   ("rendertype_gui",                        "rendertype_gui"),
    "gui_textured_premultiplied_alpha": ("rendertype_gui",                        "rendertype_gui"),
    "crosshair":                        ("rendertype_gui",                        "rendertype_gui"),
    "vignette":                         ("rendertype_gui_overlay",                "rendertype_gui_overlay"),
    "panorama":                         ("blit_screen",                           "blit_screen"),
    "mojang_logo":                      ("blit_screen",                           "blit_screen"),
    "text":                             ("rendertype_text",                       "rendertype_text"),
    "text_see_through":                 ("rendertype_text_see_through",           "rendertype_text_see_through"),
    "text_intensity":                   ("rendertype_text_intensity",             "rendertype_text_intensity"),
    "text_intensity_see_through":       ("rendertype_text_intensity_see_through", "rendertype_text_intensity_see_through"),
    "text_background":                  ("rendertype_text_background",            "rendertype_text_background"),
    "text_background_see_through":      ("rendertype_text_background_see_through","rendertype_text_background_see_through"),
    "text_polygon_offset":              ("rendertype_text",                       "rendertype_text"),
    "sky":                              ("rendertype_solid",                      "rendertype_solid"),
    "stars":                            ("rendertype_solid",                      "rendertype_solid"),
    "celestial":                        ("rendertype_solid",                      "rendertype_solid"),
    "end_sky":                          ("rendertype_solid",                      "rendertype_solid"),
    "sunrise_sunset":                   ("rendertype_solid",                      "rendertype_solid"),
    "flat_clouds":                      ("rendertype_clouds",                     "rendertype_clouds"),
    "solid":                            ("rendertype_solid",                      "rendertype_solid"),
    "cutout":                           ("rendertype_cutout",                     "rendertype_cutout"),
    "cutout_mipped":                    ("rendertype_cutout_mipped",              "rendertype_cutout_mipped"),
    "translucent":                      ("rendertype_translucent",                "rendertype_translucent"),
    "translucent_moving_block":         ("rendertype_translucent_moving_block",   "rendertype_translucent_moving_block"),
    "tripwire":                         ("rendertype_tripwire",                   "rendertype_tripwire"),
    "water_mask":                       ("rendertype_water_mask",                 "rendertype_water_mask"),
    "crumbling":                        ("rendertype_crumbling",                  "rendertype_crumbling"),
    "entity_solid":                     ("rendertype_entity_solid",               "rendertype_entity_solid"),
    "entity_cutout":                    ("rendertype_entity_cutout",              "rendertype_entity_cutout"),
    "entity_cutout_no_cull":            ("rendertype_entity_cutout_no_cull",      "rendertype_entity_cutout_no_cull"),
    "entity_cutout_no_cull_z_offset":   ("rendertype_entity_cutout_no_cull_z_offset","rendertype_entity_cutout_no_cull_z_offset"),
    "entity_translucent":               ("rendertype_entity_translucent",         "rendertype_entity_translucent"),
    "entity_translucent_emissive":      ("rendertype_entity_translucent_emissive","rendertype_entity_translucent_emissive"),
    "entity_no_outline":                ("rendertype_entity_no_outline",          "rendertype_entity_no_outline"),
    "entity_shadow":                    ("rendertype_entity_shadow",              "rendertype_entity_shadow"),
    "entity_decal":                     ("rendertype_entity_decal",               "rendertype_entity_decal"),
    "entity_smooth_cutout":             ("rendertype_entity_smooth_cutout",       "rendertype_entity_smooth_cutout"),
    "entity_solid_offset_forward":      ("rendertype_entity_solid",               "rendertype_entity_solid"),
    "block_screen_effect":              ("rendertype_entity_solid",               "rendertype_entity_solid"),
    "fire_screen_effect":               ("rendertype_entity_solid",               "rendertype_entity_solid"),
    "eyes":                             ("rendertype_eyes",                       "rendertype_eyes"),
    "energy_swirl":                     ("rendertype_energy_swirl",               "rendertype_energy_swirl"),
    "breeze_wind":                      ("rendertype_breeze_wind",                "rendertype_breeze_wind"),
    "armor_cutout_no_cull":             ("rendertype_armor_cutout_no_cull",       "rendertype_armor_cutout_no_cull"),
    "armor_decal_cutout_no_cull":       ("rendertype_armor_cutout_no_cull",       "rendertype_armor_cutout_no_cull"),
    "armor_translucent":                ("rendertype_entity_translucent_cull",    "rendertype_entity_translucent_cull"),
    "glint":                            ("rendertype_glint",                      "rendertype_glint"),
    "leash":                            ("rendertype_leash",                      "rendertype_leash"),
    "lightning":                        ("rendertype_lightning",                  "rendertype_lightning"),
    "beacon_beam_opaque":               ("rendertype_beacon_beam",                "rendertype_beacon_beam"),
    "beacon_beam_translucent":          ("rendertype_beacon_beam",                "rendertype_beacon_beam"),
    "end_portal":                       ("rendertype_end_portal",                 "rendertype_end_portal"),
    "end_gateway":                      ("rendertype_end_portal",                 "rendertype_end_portal"),
    "world_border":                     ("rendertype_world_border",               "rendertype_world_border"),
    "secondary_block_outline":          ("rendertype_outline",                    "rendertype_outline"),
    "outline_cull":                     ("rendertype_outline",                    "rendertype_outline"),
    "outline_no_cull":                  ("rendertype_outline",                    "rendertype_outline"),
    "lines":                            ("rendertype_lines",                      "rendertype_lines"),
    "line_strip":                       ("rendertype_lines",                      "rendertype_lines"),
    "wireframe":                        ("rendertype_lines",                      "rendertype_lines"),
    "opaque_particle":                  ("particle",                              "particle"),
    "translucent_particle":             ("particle",                              "particle"),
    "debug_filled_box":                 ("position_color",                        "position_color"),
    "debug_line_strip":                 ("position_color",                        "position_color"),
    "debug_quads":                      ("position_color",                        "position_color"),
    "debug_section_quads":              ("position_color",                        "position_color"),
    "debug_structure_quads":            ("position_color",                        "position_color"),
    "debug_triangle_fan":               ("position_color",                        "position_color"),
}

# ---------------------------------------------------------------------------
# Patcher GLSL OpenGL 150 → Vulkan 450
# ---------------------------------------------------------------------------

# Regex para declaração 'uniform TYPE NAME[ARRAY];' (sem layout já presente)
# Captura: group(1)=TYPE (pode ter espaços: "mat4", "vec4", etc.)
#          group(2)=NAME
#          group(3)=ARRAY opcional (ex: "[16]")
RE_UNIFORM = re.compile(
    r'^(?!.*\blayout\b)[ \t]*uniform\s+'
    r'((?:\w+\s+)*\w+)\s+'    # tipo (greedy, captura "mat4 " etc)
    r'(\w+)'                   # nome
    r'(\s*\[\s*\d+\s*\])?'   # array opcional
    r'\s*(?:=\s*[^;]+)?'      # inicializador opcional (ignoramos)
    r'\s*;[ \t]*$',
    re.MULTILINE
)

# Regex para 'in TYPE NAME;' ou 'attribute TYPE NAME;' sem layout
RE_IN = re.compile(
    r'^(?!.*\blayout\b)[ \t]*(?:(?:\w+\s+)*)(?:in|attribute)\s+'
    r'((?:\w+\s+)*\w+)\s+(\w+)\s*;[ \t]*$',
    re.MULTILINE
)

# Regex para 'out TYPE NAME;' ou 'flat out TYPE NAME;' sem layout
RE_OUT = re.compile(
    r'^(?!.*\blayout\b)[ \t]*(?:(?:\w+\s+)*)out\s+'
    r'((?:\w+\s+)*\w+)\s+(\w+)\s*;[ \t]*$',
    re.MULTILINE
)

# 'varying TYPE NAME;' (GLSL 110/120 leftovers)
RE_VARYING = re.compile(
    r'^(?!.*\blayout\b)[ \t]*varying\s+'
    r'((?:\w+\s+)*\w+)\s+(\w+)\s*;[ \t]*$',
    re.MULTILINE
)


def patch_glsl(source: str, stage: str) -> str:
    """
    Converte GLSL OpenGL 150 → Vulkan 450.
    stage: 'vert' ou 'frag'
    """
    # 0. Resolver #moj_import
    def resolve_import(m):
        filename = m.group(1)
        import_path = os.path.join(PREPROCESSED_DIR, filename)
        if os.path.exists(import_path):
            with open(import_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            # Remover #version dos includes
            content = re.sub(r'#version\s+\d+\b[^\n]*\n', '', content)
            return content
        else:
            return f'// ERROR: moj_import "{filename}" not found\n'
    source = re.sub(r'#moj_import\s+<([^>]+)>', resolve_import, source)

    # 1. Versão
    source = re.sub(r'#version\s+\d+\b[^\n]*', '#version 450', source)
    source = '#version 450\n#extension GL_ARB_shader_draw_parameters : require\n' + source[source.find('\n')+1:] if '#version' in source else source

    # Substituir gl_VertexID por gl_VertexIndex
    source = source.replace('gl_VertexID', 'gl_VertexIndex')

    # 2. Recolher uniformes e substituí-los
    ubo_members = []          # linhas para o UBO block
    sampler_binding = [1]     # binding 0 reservado para UBO
    lines_to_remove = set()   # índices de linhas a remover (após collect)

    def handle_uniform(m):
        type_str = m.group(1).strip()
        name_str = m.group(2).strip()
        array_str = (m.group(3) or '').strip()

        if SAMPLER_TYPES.search(type_str):
            # Sampler → layout(binding=N) uniform sampler...
            b = sampler_binding[0]
            sampler_binding[0] += 1
            return f'layout(binding = {b}) uniform {type_str} {name_str}{array_str};'
        else:
            # Não-sampler → vai para UBO (sem inicializador, que não é válido em UBO)
            ubo_members.append(f'    {type_str} {name_str}{array_str};')
            return ''   # remover do local original

    source = RE_UNIFORM.sub(handle_uniform, source)

    # 3. in / attribute → layout(location=N) in
    in_loc = [0]
    def handle_in(m):
        loc = in_loc[0]; in_loc[0] += 1
        return f'layout(location = {loc}) in {m.group(1).strip()} {m.group(2).strip()};'

    source = RE_IN.sub(handle_in, source)

    # 4. out → layout(location=N) out
    out_loc = [0]
    def handle_out(m):
        loc = out_loc[0]; out_loc[0] += 1
        return f'layout(location = {loc}) out {m.group(1).strip()} {m.group(2).strip()};'

    source = RE_OUT.sub(handle_out, source)

    # 5. varying → in (frag) ou out (vert)
    var_loc = [0]
    def handle_varying(m):
        loc = var_loc[0]; var_loc[0] += 1
        keyword = 'out' if stage == 'vert' else 'in'
        return f'layout(location = {loc}) {keyword} {m.group(1).strip()} {m.group(2).strip()};'

    source = RE_VARYING.sub(handle_varying, source)

    # 6. gl_FragColor → declaração de saída + substituição
    if 'gl_FragColor' in source:
        # Inserir declaração logo a seguir ao #version
        source = re.sub(
            r'(#version\s+450[^\n]*\n)',
            r'\1layout(location = 0) out vec4 fragColor;\n',
            source
        )
        source = source.replace('gl_FragColor', 'fragColor')

    # 7. Inserir UBO block logo a seguir ao #version (se houver membros)
    if ubo_members:
        ubo_block = (
            'layout(std140, binding = 0) uniform VKUniforms {\n'
            + '\n'.join(ubo_members)
            + '\n};\n'
        )
        source = re.sub(
            r'(#version\s+450[^\n]*\n(?:layout\([^)]*\)\s*out[^\n]*\n)*)',
            r'\1' + ubo_block,
            source,
            count=1
        )

    # 8. Limpar linhas vazias excessivas (linhas onde uniforms foram removidos)
    source = re.sub(r'\n{3,}', '\n\n', source)

    return source


# ---------------------------------------------------------------------------
# Validação SPIR-V
# ---------------------------------------------------------------------------
def validate_spv(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            data = f.read(4)
        if len(data) < 4:
            return False
        return struct.unpack('<I', data)[0] == SPIRV_MAGIC
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Compilação: patchar → ficheiro temporário → glslc → validar
# ---------------------------------------------------------------------------
def compile_one(src_path: str, out_path: str, stage: str) -> tuple[bool, str]:
    """
    Retorna (sucesso, mensagem_erro).
    """
    with open(src_path, 'r', encoding='utf-8', errors='replace') as f:
        original = f.read()

    # Patch sempre (detecta #version < 400 ou ausência de layout)
    needs_patch = bool(re.search(r'#version\s+[12]\d{2}\b', original)) \
               or ('layout' not in original and ('in ' in original or 'uniform ' in original))

    if needs_patch:
        patched = patch_glsl(original, stage)
    else:
        patched = original

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Escrever em ficheiro temporário
    suffix = '.vert.glsl' if stage == 'vert' else '.frag.glsl'
    with tempfile.NamedTemporaryFile(mode='w', suffix=suffix,
                                     delete=False, encoding='utf-8') as tmp:
        tmp.write(patched)
        tmp_path = tmp.name

    try:
        cmd = ['glslc', f'-fshader-stage={stage}',
               '--target-env=vulkan1.1', '-O',
               tmp_path, '-o', out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if r.returncode == 0 and validate_spv(out_path):
            return True, "OK"

        err = (r.stderr or r.stdout or '(sem output)').strip()

        # Segunda tentativa sem -O
        cmd2 = [c for c in cmd if c != '-O']
        r2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
        if r2.returncode == 0 and validate_spv(out_path):
            return True, "OK (sem -O)"

        # Log do shader patchado para diagnóstico
        diag_path = out_path + '.patched.glsl'
        with open(diag_path, 'w', encoding='utf-8') as f:
            f.write(patched)

        return False, err[:300]

    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # Verificar glslc
    if not shutil.which('glslc'):
        print("ERROR: glslc não encontrado no PATH.")
        print("  sudo apt-get install -y shaderc  ou  instalar via SDK Vulkan")
        sys.exit(1)

    ver = subprocess.run(['glslc', '--version'], capture_output=True, text=True)
    print(f"glslc: {ver.stdout.strip() or ver.stderr.strip()}")

    # Verificar preprocessed/
    if not os.path.isdir(PREPROCESSED_DIR):
        print(f"ERROR: preprocessed/ não encontrado em {PREPROCESSED_DIR}")
        print("  Extrai vulkanmod_build_final.zip para /tmp/vulkanmod_build_final/")
        sys.exit(1)

    available = set(os.listdir(PREPROCESSED_DIR))
    print(f"Ficheiros em preprocessed/: {len(available)}")
    print(f"Output → {OUTPUT_BASE}")
    print(f"Pipelines: {len(PIPELINE_MAP)}")
    print()

    stats = {'ok': 0, 'skip': 0, 'fail': 0, 'missing': 0}
    failures = []

    for pipeline in sorted(PIPELINE_MAP):
        vsh_name, fsh_name = PIPELINE_MAP[pipeline]

        out_dir  = os.path.join(OUTPUT_BASE, pipeline)
        vert_out = os.path.join(out_dir, f"{pipeline}.vert.spv")
        frag_out = os.path.join(out_dir, f"{pipeline}.frag.spv")

        # Skip se SPVs válidos já existem
        if validate_spv(vert_out) and validate_spv(frag_out):
            print(f"  SKIP  {pipeline}")
            stats['skip'] += 1
            continue

        vsh_file = f"{vsh_name}.vsh"
        fsh_file = f"{fsh_name}.fsh"

        missing = [f for f in [vsh_file, fsh_file] if f not in available]
        if missing:
            print(f"  MISS  {pipeline}  ({', '.join(missing)})")
            stats['missing'] += 1
            failures.append((pipeline, 'SOURCE_MISSING', ', '.join(missing)))
            continue

        vert_src = os.path.join(PREPROCESSED_DIR, vsh_file)
        frag_src = os.path.join(PREPROCESSED_DIR, fsh_file)

        ok_v, msg_v = compile_one(vert_src, vert_out, 'vert')
        ok_f, msg_f = compile_one(frag_src, frag_out, 'frag')

        if ok_v and ok_f:
            print(f"  OK    {pipeline}")
            stats['ok'] += 1
        else:
            parts = []
            if not ok_v: parts.append(f"VERT:{msg_v[:80]}")
            if not ok_f: parts.append(f"FRAG:{msg_f[:80]}")
            print(f"  FAIL  {pipeline}  |  {' | '.join(parts)}")
            stats['fail'] += 1
            failures.append((pipeline, 'COMPILE_FAIL', ' | '.join(parts)))

    # Relatório
    total_spv = (stats['ok'] + stats['skip']) * 2
    print()
    print("=" * 60)
    print(f"  ✅ Compilados : {stats['ok']}  ({stats['ok']*2} SPVs)")
    print(f"  ⏭  Ignorados  : {stats['skip']}")
    print(f"  ❌ Falhados   : {stats['fail']}")
    print(f"  ⚠  Ausentes  : {stats['missing']}")
    print(f"  SPVs totais   : {total_spv}")
    print("=" * 60)

    if failures:
        print()
        print("DETALHES DAS FALHAS:")
        for p, kind, detail in failures:
            print(f"  [{kind}] {p}: {detail[:120]}")
        print()
        print(f"Shaders patchados com erro gravados como *.spv.patched.glsl")
        print(f"  find {OUTPUT_BASE} -name '*.patched.glsl' | head -5")

    if stats['ok'] > 0:
        print()
        print("COMMIT:")
        print(f"  git add {OUTPUT_BASE}/")
        print('  git commit -m "Add precompiled SPIR-V shaders for Android pipeline"')
        print("  git push")

    sys.exit(0 if (stats['fail'] == 0 and stats['missing'] == 0) else 1)


if __name__ == '__main__':
    main()
