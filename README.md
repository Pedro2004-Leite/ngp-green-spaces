# NGP Green Spaces — Guia de Uso no Windows

Guia prático para criar datasets customizados e gerar renders NeRF com **Instant-NGP** no Windows. O foco principal deste projeto são **espaços interiores** (salas, corredores, átrios), com notas adicionais para espaços ao ar livre.

---

## Exemplo Real — [Convento de Cristo, Tomar](https://www.patrimoniomundialdocentro.pt/pt/patrimonio/convento-de-cristo-de-tomar/)

![Convento de Cristo, Tomar](https://www.patrimoniomundialdocentro.pt/imagens/patrimonio/top_convento_de_cristo_de_tomar_5b05f68f39dcf.jpg)

> **Convento de Cristo** (Tomar, Portugal) — Património Mundial da UNESCO desde 1983.
> Fundado em 1160 pelos Templários, o complexo combina estilos românico, gótico, manuelino e renascentista.
> A Charola (rotunda templária) e a famosa Janela do Capítulo são dois dos seus espaços interiores mais icónicos.

### Pipeline utilizado

**1. Extracção de frames e reconstrução COLMAP** a partir de um vídeo gravado no interior:

```bat
python C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py ^
  --video_in "C:\remote\ngp-green-spaces\videos\convento_cristo.mp4" ^
  --video_fps 2 ^
  --run_colmap ^
  --colmap_camera_model SIMPLE_RADIAL ^
  --aabb_scale 8 ^
  --overwrite
```

> **Nota:** O modelo `OPENCV` (padrão) falhou neste caso — apenas 2 frames foram reconstruídas.
> `SIMPLE_RADIAL` (apenas k1) é mais robusto para vídeo de telemóvel sem calibração prévia.

**Resultado:**
| Parâmetro | Valor |
|---|---|
| Frames extraídas | 100 |
| Frames registadas pelo COLMAP | 100 / 100 |
| Bundle adjustment | Convergido (`CONVERGENCE`) |
| Distorção k1 | 0.028 (razoável) |
| Focal length | 947 px (plausível para portrait 576×1024) |
| aabb_scale usado | 8 (espaço interior compacto) |

**2. Correr o NeRF:**

```bat
cd C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000
instant-ngp.exe ..\videos\transforms.json
```

### Lições aprendidas

- Para **vídeo de telemóvel** (portrait, sem calibração), usar `--colmap_camera_model SIMPLE_RADIAL`
- O modelo `OPENCV` pode sobre-ajustar os parâmetros de distorção e produzir resultados degenerados (k1 > 1)
- 2 fps num vídeo de ~50 segundos gera ~100 frames — dentro do intervalo ideal
- `aabb_scale 8` adequado para salas e espaços interiores compactos

---

## Pre-requisitos

- GPU NVIDIA RTX (3000/4000 series recomendado)
- Python 3.8 ou superior — [download aqui](https://www.python.org/downloads/) (marcar "Add python.exe to PATH" durante a instalação)
- O executável `instant-ngp.exe` está em `Instant-NGP-for-RTX-3000-and-4000/`

> COLMAP e FFmpeg **nao precisam ser instalados manualmente no Windows** — sao descarregados automaticamente pelo script quando necessarios.

---

## Instalacao

Instalar as dependencias Python a partir da pasta do instant-ngp:

```bat
cd Instant-NGP-for-RTX-3000-and-4000
pip install -r requirements.txt
```

---

## Criar um Dataset Customizado

### Opcao A — A partir de um video

Coloca o ficheiro de video na pasta de dados e corre:

```bat
cd C:\caminho\para\pasta-do-dataset
python C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py ^
  --video_in video.mp4 ^
  --video_fps 2 ^
  --run_colmap ^
  --aabb_scale 128
```

- `--video_fps 2` — extrai 2 frames por segundo; ajustar para obter 50-150 imagens no total
- `--aabb_scale 128` — recomendado para espacos ao ar livre com fundo extenso

### Opcao B — A partir de um iPhone (Record3D)

Alternativa ao COLMAP usando ARKit, mais robusta para cenas sem texturas ou com padroes repetitivos. Requer iPhone 12 Pro ou mais recente.

1. Instalar a app [Record3D](https://record3d.app/) no iPhone
2. Gravar o espaco e exportar com o formato **"Shareable/Internal format (.r3d)"**
3. Enviar o ficheiro `.r3d` para o computador
4. Renomear a extensao de `.r3d` para `.zip` e descomprimir — obtem-se uma pasta `path/to/data`
5. Correr o script de conversao:

```bat
cd C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000
python scripts\record3d2nerf.py --scene C:\caminho\para\path\to\data
```

> Se gravaste em modo **landscape** (horizontal), adicionar a flag `--rotate`:
> ```bat
> python scripts\record3d2nerf.py --scene C:\caminho\para\path\to\data --rotate
> ```

6. Correr o NeRF:

```bat
instant-ngp.exe C:\caminho\para\path\to\data
```

---

### Opcao C — A partir de fotografias

Coloca as fotos numa subpasta chamada `images` e corre:

```bat
cd C:\caminho\para\pasta-do-dataset
python C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py ^
  --colmap_matcher exhaustive ^
  --run_colmap ^
  --aabb_scale 128
```

- `--colmap_matcher exhaustive` — usar quando as fotos nao tem uma ordem sequencial
- `--colmap_matcher sequential` — usar quando as fotos foram tiradas em sequencia (como frames de video)

O script gera automaticamente um ficheiro `transforms.json` na pasta atual.

---

## Correr o NeRF

### Interface grafica (GUI)

```bat
cd C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000
instant-ngp.exe C:\caminho\para\pasta-do-dataset
```

Ou simplesmente arrastar a pasta do dataset para a janela do `instant-ngp.exe`.

### Exemplo com o dataset incluido (fox)

```bat
cd C:\remote\ngp-green-spaces\Instant-NGP-for-RTX-3000-and-4000
instant-ngp.exe data\nerf\fox
```

---

## Parametro aabb_scale

O parametro mais importante para a qualidade do NeRF. Deve ser uma potencia de 2 (1, 2, 4, 8, ..., 128).

| Cenario | aabb_scale recomendado |
|---|---|
| Objeto pequeno / cena sintetica | 1 |
| Divisao pequena (quarto, escritorio) | 4–8 |
| Divisao grande / sala com janelas | 16 |
| Interior amplo (corredor, atrio) | 32 |
| Exterior / espaco ao ar livre | 64–128 |

Para espaços interiores, **começar com `aabb_scale 16`** e ajustar: se o modelo parecer cortado, aumentar; se houver muito ruido no fundo, diminuir.

Pode ser editado diretamente no `transforms.json` sem re-correr o COLMAP:

```json
{
    "aabb_scale": 128,
    "scale": 0.33,
    "offset": [0.5, 0.5, 0.5],
    ...
}
```

---

## Dicas para bons resultados

- **50 a 150 imagens** e o intervalo ideal
- Evitar **blur de movimento** e **blur de desfoque** — tratar a captura como fotogrametria
- Todos os objetos devem estar **estaticos** durante a captura
- Lentes **grande angular** dao melhores resultados (ex: modo wide do iPhone)
- O modelo deve convergir nos primeiros **20 segundos** — se nao convergir, o problema e nos dados
- Verificar o alinhamento das cameras com "Visualize cameras" + "Visualize unit cube" no GUI
- Para iluminacao/exposicao inconsistente entre fotos, adicionar ao `transforms.json`:
  ```json
  { "n_extra_learnable_dims": 16 }
  ```
- Para remover objetos dinamicos (pessoas, carros), usar o argumento:
  ```bat
  --mask_categories person car
  ```
  (requer Detectron2 instalado)

---

## Dicas especificas para Espacos Interiores

### Captura

- Percorrer o espaco de forma **sistematica e sobreposta** — cada ponto do espaco deve aparecer em pelo menos 3 a 5 fotografias de angulos diferentes
- Incluir **vistas de canto** (olhar para os cantos da sala) para ajudar o COLMAP a triangular pontos de referencia
- Evitar fotografar **diretamente para janelas** — a diferenca de exposicao entre interior e exterior confunde o modelo; se inevitavel, ativar `n_extra_learnable_dims`
- Fotografar a **mesma area de multiplas alturas** (agachado, normal, levantado) melhora a reconstrucao 3D
- Superficies **monocromaticas lisas** (parede branca, teto uniforme) sao dificeis para o COLMAP — garantir que existem objetos ou detalhes visiveis no enquadramento

### Processamento COLMAP

Para fotografias de interiores, preferir o matcher `exhaustive` (nao sequencial):

```bat
python Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py ^
  --colmap_matcher exhaustive ^
  --run_colmap ^
  --aabb_scale 16
```

Usar `sequential` apenas se as fotos foram tiradas numa trajetoria continua e ordenada (ex: video).

### Parametros recomendados no `transforms.json` para interiores

```json
{
    "aabb_scale": 16,
    "scale": 0.33,
    "offset": [0.5, 0.5, 0.5],
    "n_extra_learnable_dims": 16
}
```

O `n_extra_learnable_dims: 16` e particularmente util em interiores com iluminacao artificial variavel (luzes direcionais, zonas de sombra).

---

## Mapa de Iluminância para Colocação de Plantas

Depois de exportar a mesh pelo GUI do Instant-NGP (secção **NeRF → Mesh**), é possível gerar
automaticamente um mapa de iluminância top-down para identificar as melhores zonas para plantas.

### Dependências

```bat
pip install trimesh pillow matplotlib numpy scipy
```

### Opcao A — Mapa de luminância relativa (sem medicoes)

Usa a textura da mesh como proxy de iluminância. Funciona sem equipamento adicional.

```bat
python scripts\illuminance_map.py --mesh dataset\mesh.obj
```

Gera `illuminance_map.png` — mapa de calor com a luminância relativa de cada zona.

### Opcao B — Mapa calibrado em lux (com luximetro)

Mede a iluminância real em alguns pontos do espaço com um luxímetro (ou app de smartphone)
e regista as posicoes normalizadas [0–1] num CSV:

```csv
x,y,lux
0.15,0.20,850
0.50,0.10,1200
0.85,0.80,180
```

- `x`, `y` — posicao no mapa, de 0 a 1 (origem: canto superior esquerdo)
- `lux` — valor medido no local correspondente

```bat
python scripts\illuminance_map.py ^
  --mesh dataset\mesh.obj ^
  --lux_refs scripts\lux_refs_example.csv ^
  --output iluminancia_lux.png
```

Gera dois ficheiros:
- `iluminancia_lux.png` — mapa contínuo em lux
- `iluminancia_lux_plantas.png` — mapa por zonas de aptidão para plantas

| Zona | Lux | Plantas adequadas |
|---|---|---|
| Sem luz | < 50 | — |
| Baixa luminosidade | 50–250 | Sansevieria, Zamioculcas, Aglaonema |
| Luminosidade média | 250–1000 | Ficus, Dracena, Pothos |
| Alta luminosidade | > 1000 | Suculentas, cactos, ervas aromáticas |

### Opcao C — Simulacao fisica com Blender (mais precisa)

Requer Blender 3.x instalado. Simula iluminação física com Cycles e gera mapa HDR.

```bat
blender --background --python scripts\blender_illuminance.py -- ^
  --mesh dataset\mesh.obj ^
  --output iluminancia_blender.png ^
  --resolution 1024 ^
  --samples 256
```

Argumentos opcionais:
- `--sun_strength 5.0` — intensidade da luz solar (W/m²·sr)
- `--samples 128` — amostras Cycles (mais amostras = menos ruido, mais lento)

> **Nota sobre precisao:** as opcoes A e B baseiam-se na aparencia da textura capturada,
> que mistura albedo do material com iluminacao real. Sao proxies razoaveis para iluminacao
> relativa entre zonas, mas nao substituem um estudo luminotecnico rigoroso.
> A opcao C simula fisicamente a propagacao da luz na geometria reconstruida.

---

## Guardar e Carregar um Modelo Treinado

No GUI, usar a secao **Snapshot**:
- **Save** — guarda o modelo treinado
- **Load** — carrega um modelo previamente guardado

---

## Controlos do GUI

| Tecla | Acao |
|---|---|
| WASD | Mover frente / esquerda / tras / direita |
| Espaco / C | Subir / descer |
| T | Pausar / retomar treino |
| Tab | Mostrar / esconder menu |
| Shift+R | Reset da camara |
| [ ] | Ver frame anterior / seguinte do dataset |
| 1-8 | Mudar modo de render |

---

## Estrutura de Pastas Esperada

```
meu-dataset/
  images/          <- fotos ou frames extraidos do video
  transforms.json  <- gerado pelo colmap2nerf.py
```

---

## Referencia Rapida de Comandos

```bat
# 1. Instalar dependencias
pip install -r Instant-NGP-for-RTX-3000-and-4000\requirements.txt

# 2a. Processar video
python Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py --video_in video.mp4 --video_fps 2 --run_colmap --aabb_scale 128

# 2b. Processar imagens
python Instant-NGP-for-RTX-3000-and-4000\scripts\colmap2nerf.py --colmap_matcher exhaustive --run_colmap --aabb_scale 128

# 2c. Processar dados do Record3D (iPhone)
python Instant-NGP-for-RTX-3000-and-4000\scripts\record3d2nerf.py --scene C:\caminho\para\dados-r3d

# 3. Correr o NeRF
Instant-NGP-for-RTX-3000-and-4000\instant-ngp.exe C:\caminho\para\pasta-do-dataset
```
