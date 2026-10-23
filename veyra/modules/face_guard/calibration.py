# veyra/modules/face_guard/calibration.py
"""Calibration locale des seuils biométriques (V0.2).

Principe : collecter des distances L2 déjà calculées pendant la surveillance
( aucune empreinte ni image n'est conservée — des scalaires uniquement ) :

- **genuine** : distances du propriétaire reconnu TRUSTED -> sa référence ;
- **impostor** : distances d'un visage classé UNKNOWN -> la référence.

À partir de ces deux distributions, on trace la courbe FAR/FRR locale et on
propose le seuil au point d'égalisation (EER — Equal Error Rate) :

- FAR(d) = fraction des impostors sous le seuil d (faux acceptés) ;
- FRR(d) = fraction des genuine au-dessus du seuil d (faux rejetés).

Ceci reste UNE calibration LOCALE de quelques dizaines d'échantillons — pas
une validation statistique sur corpus (voir docs/SECURITY.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurvePoint:
    """Un point de la courbe FAR/FRR pour un seuil donné."""

    threshold: float
    far: float
    frr: float


@dataclass(frozen=True)
class CalibrationSummary:
    """Synthèse d'une calibration à partir des échantillons collectés."""

    genuine_count: int
    impostor_count: int
    curve: tuple[CurvePoint, ...]
    eer_threshold: float | None
    eer: float | None

    @property
    def suggested_threshold(self) -> float | None:
        return self.eer_threshold


def far_frr_curve(genuine: list[float], impostors: list[float],
                  thresholds: list[float] | None = None) -> tuple[CurvePoint, ...]:
    """Courbe FAR/FRR échantillonnée sur ``thresholds`` (défaut : 0.05..1.5)."""
    if thresholds is None:
        thresholds = [round(0.05 * i, 2) for i in range(1, 31)]  # 0.05 .. 1.50
    points: list[CurvePoint] = []
    n_imp = len(impostors)
    n_gen = len(genuine)
    for t in thresholds:
        far = (sum(1 for d in impostors if d <= t) / n_imp) if n_imp else 0.0
        frr = (sum(1 for d in genuine if d > t) / n_gen) if n_gen else 0.0
        points.append(CurvePoint(threshold=t, far=far, frr=frr))
    return tuple(points)


def equal_error_point(curve: tuple[CurvePoint, ...]) -> tuple[float, float] | None:
    """Seuil et taux au point où |FAR - FRR| est minimal (EER approximatif)."""
    if not curve:
        return None
    best = min(curve, key=lambda p: abs(p.far - p.frr))
    return best.threshold, max(best.far, best.frr)


def calibrate(genuine: list[float], impostors: list[float]) -> CalibrationSummary:
    """Calcule la courbe et le point d'égalisation des échantillons."""
    curve = far_frr_curve(genuine, impostors)
    eep = equal_error_point(curve)
    return CalibrationSummary(
        genuine_count=len(genuine),
        impostor_count=len(impostors),
        curve=curve,
        eer_threshold=eep[0] if eep else None,
        eer=eep[1] if eep else None,
    )


def merge_samples(existing: dict[str, list[float]],
                  incoming: dict[str, list[float]],
                  cap: int = 500) -> dict[str, list[float]]:
    """Fusionne et borne les échantillons (persistance légère, scalaires seuls)."""
    merged: dict[str, list[float]] = {}
    for key in ("genuine", "impostor"):
        values = list(existing.get(key, [])) + list(incoming.get(key, []))
        merged[key] = values[-cap:]
    return merged
