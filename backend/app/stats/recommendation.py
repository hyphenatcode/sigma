"""Rule-based test recommendation engine (§3.3).

This is a PURE FUNCTION over variable metadata. No LLM, no data access, no I/O.
It is a direct transcription of the decision tree in §3.3 of the requirements
doc, and it deliberately refuses to guess: any input combination that does not
match a rule returns `supported=False` with an explicit reason, never a
best-guess neighbouring test (§3.3: "wrong recommendations are reputationally
worse than a 'not supported yet' message").

Assumption checking (§3.4) happens *after* this function, in
`app.stats.pipeline`, and may swap the candidate for the fallback recorded on
the returned recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.stats import registry
from app.stats.enums import MeasurementLevel, ResearchTask


class Unsupported(str):
    """Marker for readability at call sites."""


@dataclass(frozen=True)
class VariableSpec:
    """Metadata for one variable as confirmed by the user in §3.2."""

    name: str
    measurement_level: MeasurementLevel

    @property
    def is_continuous(self) -> bool:
        return self.measurement_level.is_continuous

    @property
    def is_categorical(self) -> bool:
        return self.measurement_level.is_categorical


@dataclass(frozen=True)
class RecommendationInput:
    """The §3.3 INPUT line, typed.

    `n_groups` is auto-counted from distinct values of the grouping variable and
    confirmed by the user (§3.2); it is only meaningful for a categorical IV.
    """

    task: ResearchTask
    dv: Optional[VariableSpec] = None
    ivs: tuple[VariableSpec, ...] = ()
    n_groups: Optional[int] = None
    is_paired: bool = False
    scale_items: tuple[VariableSpec, ...] = ()

    @property
    def n_ivs(self) -> int:
        return len(self.ivs)


@dataclass(frozen=True)
class Recommendation:
    """Result of the decision tree.

    `candidate` is the parametric/primary choice; `fallback` is the
    non-parametric test §3.4 switches to if normality fails. When `supported`
    is False, `reason_tr` carries the user-facing Turkish message and
    `candidate` may still name the (unimplemented) test the tree selected.
    """

    supported: bool
    candidate: Optional[str] = None
    fallback: Optional[str] = None
    reason_tr: Optional[str] = None
    rule_path: tuple[str, ...] = field(default_factory=tuple)

    @property
    def candidate_label_tr(self) -> Optional[str]:
        return registry.get(self.candidate).label_tr if self.candidate else None


_NOT_SUPPORTED_TR = (
    "Bu değişken yapısı bu sürümde desteklenmiyor. "
    "Sigma yalnızca doğruluğunu güvence altına alabildiği analizleri sunar."
)


def _unsupported(reason_tr: str, *, path: tuple[str, ...], candidate: str | None = None) -> Recommendation:
    return Recommendation(
        supported=False,
        candidate=candidate,
        reason_tr=reason_tr,
        rule_path=path,
    )


def _supported(candidate: str, path: tuple[str, ...]) -> Recommendation:
    """Wrap a decision-tree leaf, honouring the registry's v1 support gate."""
    spec = registry.get(candidate)
    if not spec.supported_in_v1:
        return _unsupported(
            f"Bu veri yapısı için önerilen analiz: {spec.label_tr}. "
            f"Ancak bu analiz Sigma'nın bu sürümünde henüz desteklenmemektedir.",
            path=path + ("unsupported_in_v1",),
            candidate=candidate,
        )
    return Recommendation(
        supported=True,
        candidate=candidate,
        fallback=spec.nonparametric_fallback,
        rule_path=path,
    )


def recommend_test(inp: RecommendationInput) -> Recommendation:
    """Apply the §3.3 decision tree. Pure; deterministic; no LLM."""

    # ---- task-keyed branches (§3.3, bottom of the pseudocode) --------------
    if inp.task is ResearchTask.SCALE_RELIABILITY:
        if len(inp.scale_items) < 2:
            return _unsupported(
                "Güvenirlik analizi için en az iki ölçek maddesi seçilmelidir.",
                path=("task=scale_reliability", "insufficient_items"),
            )
        return _supported("cronbachs_alpha", ("task=scale_reliability",))

    if inp.task is ResearchTask.FACTOR_STRUCTURE:
        return _supported("exploratory_factor_analysis", ("task=factor_structure",))

    # ---- DV-keyed branches -------------------------------------------------
    if inp.dv is None:
        return _unsupported(
            "Bu analiz için bir bağımlı değişken seçilmelidir.",
            path=("no_dv",),
        )

    if inp.n_ivs == 0:
        return _unsupported(
            "Bu analiz için en az bir bağımsız değişken seçilmelidir.",
            path=("no_iv",),
        )

    # IF dv is continuous (interval/ratio)
    if inp.dv.is_continuous:
        return _continuous_dv(inp)

    # IF dv is categorical AND iv is categorical
    if inp.dv.is_categorical:
        if all(iv.is_categorical for iv in inp.ivs):
            if inp.n_ivs != 1:
                # TODO(spec-gap): §3.3 specifies chi-square independence for a
                # categorical DV and a categorical IV, which is a 2-way
                # contingency table. Multi-way (log-linear) analysis is not in
                # the spec, so we refuse rather than collapsing factors.
                return _unsupported(
                    "Ki-kare bağımsızlık testi bu sürümde tek bir bağımsız "
                    "değişken ile çalışmaktadır.",
                    path=("dv=categorical", "iv=categorical", "n_ivs>1"),
                )
            return _supported(
                "chi_square_independence",
                ("dv=categorical", "iv=categorical", "n_ivs=1"),
            )
        return _unsupported(
            "Kategorik bir bağımlı değişken ile sürekli bir bağımsız değişkenin "
            "birlikte kullanıldığı analizler (örn. lojistik regresyon) bu sürümde "
            "desteklenmiyor.",
            path=("dv=categorical", "iv=continuous"),
        )

    return _unsupported(_NOT_SUPPORTED_TR, path=("no_rule_matched",))


def _continuous_dv(inp: RecommendationInput) -> Recommendation:
    """The `IF dv is continuous` subtree of §3.3."""
    base = ("dv=continuous",)
    categorical_ivs = [iv for iv in inp.ivs if iv.is_categorical]
    continuous_ivs = [iv for iv in inp.ivs if iv.is_continuous]

    # Mixed IV types = ANCOVA / general linear model territory, which §3.9 puts
    # explicitly in v2. Refuse rather than dropping one of the IVs.
    if categorical_ivs and continuous_ivs:
        return _unsupported(
            "Kategorik ve sürekli bağımsız değişkenlerin birlikte yer aldığı "
            "analizler (ANCOVA vb.) bu sürümde desteklenmiyor.",
            path=base + ("iv=mixed",),
        )

    # IF iv is categorical
    if categorical_ivs:
        if len(categorical_ivs) != 1:
            # TODO(spec-gap): §3.3's tree branches on a single categorical IV
            # (n_groups). Two-way/factorial ANOVA is not in the tree and is not
            # in the Phase 1 execution list, so it is refused explicitly.
            return _unsupported(
                "Birden fazla kategorik bağımsız değişken içeren analizler "
                "(iki yönlü ANOVA vb.) bu sürümde desteklenmiyor.",
                path=base + ("iv=categorical", "n_categorical_ivs>1"),
            )

        n_groups = inp.n_groups
        if n_groups is None:
            return _unsupported(
                "Grup sayısı belirlenemedi. Lütfen gruplama değişkenini onaylayın.",
                path=base + ("iv=categorical", "n_groups=unknown"),
            )
        if n_groups < 2:
            return _unsupported(
                "Karşılaştırma yapabilmek için gruplama değişkeninin en az iki "
                "düzeyi olmalıdır.",
                path=base + ("iv=categorical", "n_groups<2"),
            )

        path = base + ("iv=categorical",)
        if n_groups == 2:
            path += ("n_groups=2",)
            if inp.is_paired:
                return _supported("paired_t_test", path + ("paired",))
            return _supported("independent_t_test", path + ("independent",))

        # n_groups > 2
        path += ("n_groups>2",)
        if inp.is_paired:
            return _supported("repeated_measures_anova", path + ("paired",))
        return _supported("one_way_anova", path + ("independent",))

    # IF iv is continuous
    if continuous_ivs:
        path = base + ("iv=continuous",)

        # §3.3 pseudocode is ambiguous here: `IF n_ivs == 1` yields
        # pearson_correlation, while the following line yields
        # simple_linear_regression for "n_ivs == 1 AND iv continuous AND only
        # relationship (no grouping)". Both leaves cannot fire on the same
        # input, so we disambiguate on the user's declared research task, which
        # is the only additional information available. A user asking about a
        # *relationship* gets correlation; one asking to *predict* gets
        # regression. We never pick silently between the two.
        #
        # TODO(spec-gap): §3.3 does not state how to choose between
        # pearson_correlation and simple_linear_regression for a single
        # continuous IV. Resolved via the explicit ResearchTask input rather
        # than by extending the rule logic.
        if inp.n_ivs == 1:
            if inp.task is ResearchTask.PREDICTION:
                return _supported("simple_linear_regression", path + ("n_ivs=1", "task=prediction"))
            if inp.task in (ResearchTask.RELATIONSHIP, ResearchTask.COMPARISON):
                return _supported("pearson_correlation", path + ("n_ivs=1", "task=relationship"))
            return _unsupported(
                "Tek sürekli bağımsız değişken için lütfen analiz amacını "
                "(ilişki veya yordama) belirtin.",
                path=path + ("n_ivs=1", "task=ambiguous"),
            )

        # n_ivs > 1 — the tree has a single leaf regardless of task.
        return _supported("multiple_linear_regression", path + ("n_ivs>1",))

    return _unsupported(_NOT_SUPPORTED_TR, path=base + ("no_rule_matched",))
