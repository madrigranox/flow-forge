"""
viewport.py — Transformacao explicita entre o espaco do MODELO e o da VISTA.

Invariante do projeto: o modelo e o unico dono das coordenadas. O layout calcula
x/y absolutos em espaco de modelo, o renderizador desenha sempre em 1:1 e o zoom
e aplicado depois, escalando o canvas a partir da origem (0, 0).

Logo, para um zoom `scale`:

    coordenada de canvas = coordenada de modelo * scale

Esta classe torna essa relacao explicita e, principalmente, inversivel: toda
entrada (clique, arraste, menu de contexto) passa por `to_model()` antes de ser
comparada com o modelo. Sem isso, qualquer zoom diferente de 100% resolve
cliques contra um sistema de coordenadas que nao e o que esta na tela — e um
arraste grava a posicao errada de volta no documento.
"""

# Um fluxo de 28 nós em 7 colunas dá ~2600x4400px. Com piso em 30% ele não
# cabia na tela em NENHUM zoom — e para um mapa de processo, ver o todo é a
# função. O piso agora alcança documentos grandes.
MIN_SCALE = 0.08
MAX_SCALE = 3.0

# Folga de toque em PIXELS DE TELA. Convertida para modelo pelo viewport, ela
# vale o mesmo para o dedo/mouse em qualquer zoom (em 300% o alvo nao fica
# "grudento", em 30% alvos finos continuam alcancaveis).
TOUCH_SLOP_PX = 5


class Viewport:
    """Transformacao de vista (zoom uniforme com origem em 0,0)."""

    def __init__(self, scale=1.0):
        self.scale = self._clamp(scale)

    # ── Escala ─────────────────────────────────────────────

    @staticmethod
    def _clamp(scale):
        return max(MIN_SCALE, min(MAX_SCALE, scale))

    def set_scale(self, scale):
        """Define o zoom absoluto (com limites). Retorna o valor aplicado."""
        self.scale = self._clamp(scale)
        return self.scale

    def apply_factor(self, factor):
        """Multiplica o zoom atual por um fator. Retorna o valor aplicado."""
        return self.set_scale(self.scale * factor)

    def reset(self):
        self.scale = 1.0
        return self.scale

    @property
    def percent(self):
        return int(round(self.scale * 100))

    # ── Modelo → Vista ─────────────────────────────────────

    def to_view(self, x, y):
        return x * self.scale, y * self.scale

    def to_view_len(self, d):
        return d * self.scale

    def to_view_points(self, pts):
        """Converte uma polilinha achatada [x1,y1,x2,y2,...] para a vista."""
        s = self.scale
        return [v * s for v in pts]

    # ── Vista → Modelo ─────────────────────────────────────

    def to_model(self, cx, cy):
        return cx / self.scale, cy / self.scale

    def to_model_len(self, d):
        return d / self.scale

    def event_to_model(self, canvas, event):
        """Converte um evento de mouse do Tk direto para coordenadas de modelo.

        `canvasx/canvasy` ja descontam o scroll; a divisao pela escala desfaz o
        zoom. Este e o unico caminho de entrada que a edicao deve usar.
        """
        return self.to_model(canvas.canvasx(event.x), canvas.canvasy(event.y))

    # ── Folga de toque ─────────────────────────────────────

    def touch_slop(self, px=TOUCH_SLOP_PX):
        """Folga de toque em unidades de MODELO, constante na tela."""
        return px / self.scale
